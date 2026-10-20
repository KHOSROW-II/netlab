"""HTTP routes for the NetLab web UI."""
import contextlib
import dataclasses
import io
import re
import threading
from ipaddress import IPv4Network, AddressValueError
from pathlib import Path
from typing import Optional

import docker
from docker.errors import APIError, NotFound
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import __version__
from ..cluster import Cluster
from ..doctor import run_checks, run_fixes
from ..exceptions import ConfigurationError
from ..firewall import FirewallManager
from ..ipam import (
    IPv4Class, analyze_ipv4, analyze_ipv6,
    split_by_count, split_subnet,
)
from ..topology import (
    GroupSpec, LabTopology, RouterSpec, ServiceSpec, TopologyType,
    load_topology,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()
_lock = threading.Lock()
_state: dict = {"topology_file": None, "topology": None}
_validation_cache: dict = {}


# --- helpers ----------------------------------------------------------------

def _project_root() -> Optional[Path]:
    try:
        return Path(__file__).resolve().parents[3]
    except IndexError:
        return None


def _discover_topologies() -> list[dict]:
    results: list[dict] = []
    seen: set[Path] = set()
    dirs = [Path.cwd()]
    root = _project_root()
    if root and root.exists() and root != Path.cwd():
        dirs.append(root)
    for base in dirs:
        for pattern in ("examples/*.yaml", "examples/*.yml", "*.yaml", "*.yml"):
            for p in sorted(base.glob(pattern)):
                try:
                    key = p.resolve()
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                results.append({"path": str(p), "name": p.stem})
    return results


def _container_dict(c) -> dict:
    net_info = c.attrs.get("NetworkSettings", {}).get("Networks", {})
    ips = {
        n: d.get("IPAddress", "")
        for n, d in net_info.items() if d.get("IPAddress")
    }
    return {
        "name": c.name,
        "label": c.name.replace("netlab-", ""),
        "role": c.labels.get("netlab.role", "host"),
        "group": c.labels.get("netlab.group"),
        "service": c.labels.get("netlab.service"),
        "status": c.status,
        "ips": ips,
    }


def _get_containers(topology_name: Optional[str]):
    try:
        client = docker.from_env()
    except Exception:
        return []
    filters = (
        {"label": f"netlab={topology_name}"}
        if topology_name else {"label": "netlab"}
    )
    try:
        return client.containers.list(all=True, filters=filters)
    except APIError:
        return []


def _safe_name(name: str) -> str:
    if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", name):
        raise HTTPException(
            status_code=400,
            detail="Name must be 1-64 chars, letters/digits/dash/underscore",
        )
    return name


def _nuclear_cleanup() -> tuple[int, int]:
    cr = nr = 0
    try:
        client = docker.from_env()
    except Exception:
        return 0, 0
    try:
        for c in client.containers.list(all=True, filters={"label": "netlab"}):
            try:
                c.remove(force=True); cr += 1
            except Exception:
                pass
    except Exception:
        pass
    try:
        for net in client.networks.list():
            name = net.name
            label = net.labels.get("netlab") if net.labels else None
            if name.startswith("netlab-") or label:
                try:
                    net.remove(); nr += 1
                except Exception:
                    pass
    except Exception:
        pass
    return cr, nr


def _read_real_networks(topology_name: Optional[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        client = docker.from_env()
    except Exception:
        return out
    try:
        if topology_name:
            nets = client.networks.list(
                filters={"label": f"netlab={topology_name}"}
            )
        else:
            nets = client.networks.list(filters={"label": "netlab"})
    except APIError:
        return out
    for net in nets:
        cfg = (net.attrs.get("IPAM", {}).get("Config") or [{}])[0]
        members = []
        for cid, cdata in (net.attrs.get("Containers") or {}).items():
            members.append(cdata.get("Name", cid[:12]))
        out[net.name] = {
            "name": net.name,
            "subnet": cfg.get("Subnet"),
            "gateway": cfg.get("Gateway"),
            "driver": net.attrs.get("Driver"),
            "id": net.id[:12],
            "members": members,
        }
    return out


def _read_container_interfaces(container) -> list[dict]:
    nets = container.attrs.get("NetworkSettings", {}).get("Networks", {})
    interfaces = []
    for net_name, data in nets.items():
        if net_name == "bridge":
            continue
        ip = data.get("IPAddress", "")
        if not ip:
            continue
        interfaces.append({
            "network": net_name,
            "ip": ip,
            "prefix": data.get("IPPrefixLen"),
            "gateway": data.get("Gateway"),
            "mac": data.get("MacAddress"),
        })
    return interfaces


# --- editor models ---------------------------------------------------------

class EditorGroup(BaseModel):
    name: str
    subnet: str
    host_count: int = Field(ge=1, le=30)
    start_offset: int = 10
    gateway_offset: int = 1
    topology: str = "bus"
    dns_servers: list[str] = []
    search_domains: list[str] = []


class EditorRouter(BaseModel):
    name: str
    connects: list[str] = []
    ip_suffix: int = Field(254, ge=2, le=254)
    image: str = "nicolaka/netshoot:latest"


class EditorService(BaseModel):
    type: str = "dnsmasq"
    group: str
    ip_suffix: int = Field(250, ge=2, le=254)
    upstream: str = "8.8.8.8"
    dhcp_range: list[int] = Field(default_factory=lambda: [100, 200])


class EditorTopology(BaseModel):
    name: str = "netlab-editor"
    image: str = "nicolaka/netshoot:latest"
    groups: list[EditorGroup] = []
    routers: list[EditorRouter] = []
    services: list[EditorService] = []


def _editor_to_labtopology(e: EditorTopology) -> LabTopology:
    groups = [
        GroupSpec(
            name=g.name, subnet=g.subnet, host_count=g.host_count,
            start_offset=g.start_offset, gateway_offset=g.gateway_offset,
            topology=TopologyType(g.topology),
            dns_servers=tuple(g.dns_servers),
            search_domains=tuple(g.search_domains),
        ) for g in e.groups
    ]
    routers = [
        RouterSpec(name=r.name, connects=tuple(r.connects),
                   ip_suffix=r.ip_suffix, image=r.image) for r in e.routers
    ]
    services = [
        ServiceSpec(type=s.type, group=s.group, ip_suffix=s.ip_suffix,
                    upstream=s.upstream, dhcp_range=tuple(s.dhcp_range))
        for s in e.services
    ]
    topo = LabTopology(name=e.name, image=e.image,
                       groups=groups, routers=routers, services=services)
    topo.validate()
    return topo


def _resolve_subnet(ip: str, subnet: Optional[str]) -> Optional[str]:
    if not subnet:
        return None
    s = subnet.strip()
    if not s:
        return None
    if s.startswith("/"):
        return ip + s
    if "/" in s:
        return s
    try:
        prefix = IPv4Network(f"0.0.0.0/{s}").prefixlen
        return f"{ip}/{prefix}"
    except Exception:
        return s


def _dc(obj) -> dict:
    if dataclasses.is_dataclass(obj):
        out = {}
        for f in dataclasses.fields(obj):
            v = getattr(obj, f.name)
            if isinstance(v, IPv4Class):
                out[f.name] = v.value
            elif v is None:
                out[f.name] = None
            elif isinstance(v, (str, int, float, bool, list, dict)):
                out[f.name] = v
            else:
                out[f.name] = str(v)
        return out
    return obj


# --- pages -----------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"version": __version__, "topologies": _discover_topologies()},
    )


# --- read endpoints --------------------------------------------------------
# These three were accidentally removed in the previous rewrite.
# They are required by app.js (refreshStatus, refreshRouting) and by
# the Editor "Load…" dropdown.

@router.get("/api/topologies")
def list_topologies():
    return {"topologies": _discover_topologies()}


@router.get("/api/status")
def get_status():
    topo = _state.get("topology")
    name = topo.name if topo else None
    containers = _get_containers(name)
    if not name and containers:
        names = {c.labels.get("netlab") for c in containers
                 if c.labels.get("netlab")}
        if len(names) == 1:
            name = names.pop()
    groups: dict[str, list] = {}
    routers: list = []
    services: list = []
    placeholders: list = []
    for c in containers:
        d = _container_dict(c)
        if d["role"] == "router":
            routers.append(d)
        elif d["role"] == "service":
            services.append(d)
        elif d["role"] in ("switch", "hub", "ap"):
            placeholders.append(d)
        elif d["group"]:
            groups.setdefault(d["group"], []).append(d)
    return {
        "cluster": name or "(none)",
        "topology_file": _state.get("topology_file"),
        "groups": [
            {"name": g, "containers": sorted(cs, key=lambda c: c["name"])}
            for g, cs in sorted(groups.items())
        ],
        "routers": sorted(routers, key=lambda c: c["name"]),
        "services": sorted(services, key=lambda c: c["name"]),
        "placeholders": sorted(placeholders, key=lambda c: c["name"]),
    }


@router.get("/api/routing")
def routing_status():
    topo = _state.get("topology")
    if topo is None:
        return {"needed": False, "enabled": True, "value": "n/a",
                "can_fix": False, "hint": ""}
    fm = FirewallManager(topo)
    if not fm.has_routers():
        return {"needed": False, "enabled": True, "value": "n/a",
                "can_fix": False, "hint": ""}
    state = fm.state()
    return {
        "needed": True,
        "enabled": state.value == "0",
        "value": state.value,
        "can_fix": state.can_change,
        "hint": state.hint,
    }


# --- graph -----------------------------------------------------------------

@router.get("/api/graph")
def graph():
    topo = _state.get("topology")
    name = topo.name if topo else None
    containers = _get_containers(name)
    real_nets = _read_real_networks(name)

    # If Docker has no containers, the cluster is gone (destroyed via CLI
    # or another window). Clear stale state so the UI shows an empty view.
    if not containers:
        _state["topology"] = None
        _state["topology_file"] = None
        return {
            "cluster": "(none)",
            "nodes": [],
            "edges": [],
            "networks": [],
            "groups": [],
        }

    nodes = []
    for c in containers:
        d = _container_dict(c)
        ifaces = _read_container_interfaces(c)
        for iface in ifaces:
            meta = real_nets.get(iface["network"], {})
            iface["subnet"] = meta.get("subnet")
        d["interfaces"] = ifaces
        nodes.append(d)

    edges: list[dict] = []
    seen: set[tuple] = set()
    for net_name, meta in real_nets.items():
        on_net = [
            n for n in nodes
            if any(i["network"] == net_name for i in n["interfaces"])
        ]
        if len(on_net) < 2:
            continue
        central = next(
            (n for n in on_net
             if n["role"] in ("switch", "hub", "ap")),
            None,
        )
        def add_edge(a_name: str, b_name: str):
            if a_name == b_name:
                return
            key = tuple(sorted([a_name, b_name])) + (net_name,)
            if key in seen:
                return
            seen.add(key)
            edges.append({
                "id": f"{key[0]}__{key[1]}__{net_name}",
                "source": a_name,
                "target": b_name,
                "kind": "lan",
                "network": net_name,
                "subnet": meta.get("subnet"),
                "gateway": meta.get("gateway"),
            })
        if central is not None:
            for n in on_net:
                if n["name"] != central["name"]:
                    add_edge(n["name"], central["name"])
        else:
            for i in range(len(on_net)):
                for j in range(i + 1, len(on_net)):
                    add_edge(on_net[i]["name"], on_net[j]["name"])

    # Only return groups that actually have containers in Docker.
    groups_meta = []
    if topo is not None:
        for g in topo.groups:
            has_nodes = any(n.get("group") == g.name for n in nodes)
            if has_nodes:
                groups_meta.append({
                    "name": g.name,
                    "subnet": g.subnet,
                    "type": g.topology.value,
                    "host_count": g.host_count,
                })
    else:
        # No stored topology: rebuild minimal metadata from live containers.
        live_groups = {n["group"] for n in nodes if n.get("group")}
        for gname in sorted(live_groups):
            subnet = None
            for net_name, meta in real_nets.items():
                if net_name == f"netlab-{gname}":
                    subnet = meta.get("subnet")
                    break
            groups_meta.append({
                "name": gname,
                "subnet": subnet,
                "type": "unknown",
                "host_count": sum(1 for n in nodes
                                  if n.get("group") == gname),
            })

    return {
        "cluster": name or "(none)",
        "nodes": nodes,
        "edges": edges,
        "networks": list(real_nets.values()),
        "groups": groups_meta,
    }


# --- validation ------------------------------------------------------------

def _container_ip(container, network_name: str) -> Optional[str]:
    nets = container.attrs.get("NetworkSettings", {}).get("Networks", {})
    data = nets.get(network_name)
    return data.get("IPAddress") if data else None


def _run_ping(client, src_name: str, target_ip: str) -> tuple[bool, float]:
    import time
    try:
        c = client.containers.get(src_name)
    except NotFound:
        return False, 0.0
    t0 = time.time()
    r = c.exec_run(["ping", "-c", "1", "-W", "2", target_ip])
    dt = (time.time() - t0) * 1000.0
    return r.exit_code == 0, round(dt, 2)


@router.post("/api/validate")
def validate(body: dict):
    topo = _state.get("topology")
    name = topo.name if topo else None
    containers = _get_containers(name)
    if not containers:
        return {"tests": [],
                "summary": {"total": 0, "passed": 0, "failed": 0},
                "detail": "no containers running"}
    try:
        client = docker.from_env()
    except Exception as exc:
        raise HTTPException(500, detail=f"Docker unavailable: {exc}")

    real_nets = _read_real_networks(name)
    target_group = body.get("group") if isinstance(body, dict) else None
    tests: list[dict] = []
    for net_name, meta in real_nets.items():
        if target_group and target_group not in net_name:
            continue
        ip_map = {}
        for c in containers:
            ip = _container_ip(c, net_name)
            if ip:
                ip_map[c.name] = ip
        names = sorted(ip_map.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                ok, rtt = _run_ping(client, a, ip_map[b])
                tests.append({
                    "network": net_name,
                    "from": a, "to": b,
                    "from_ip": ip_map[a], "to_ip": ip_map[b],
                    "ok": ok, "rtt_ms": rtt if ok else None,
                })

    passed = sum(1 for t in tests if t["ok"])
    _validation_cache[name or ""] = {
        "tests": tests, "passed": passed, "total": len(tests),
    }
    return {
        "tests": tests,
        "summary": {"total": len(tests), "passed": passed,
                    "failed": len(tests) - passed},
    }


@router.get("/api/validate/last")
def validate_last():
    topo = _state.get("topology")
    key = topo.name if topo else ""
    return _validation_cache.get(
        key, {"tests": [],
              "summary": {"total": 0, "passed": 0, "failed": 0}}
    )


# --- editor endpoints ------------------------------------------------------

@router.post("/api/editor/load")
def editor_load(body: dict):
    path = body.get("path")
    if not path:
        raise HTTPException(400, detail="path required")
    try:
        topo = load_topology(path)
    except ConfigurationError as exc:
        raise HTTPException(400, detail=str(exc))

    nodes: list[dict] = []
    edges: list[dict] = []
    y = 80
    for i, g in enumerate(topo.groups):
        nid = f"group-{i + 1}"
        net = IPv4Network(g.subnet, strict=False)
        hosts = [
            {"index": k,
             "ip": str(net.network_address + g.start_offset + (k - 1))}
            for k in range(1, g.host_count + 1)
        ]
        nodes.append({
            "id": nid, "kind": "group", "x": 80, "y": y,
            "name": g.name, "subnet": g.subnet,
            "host_count": g.host_count,
            "start_offset": g.start_offset,
            "gateway_offset": g.gateway_offset,
            "topology": g.topology.value,
            "dns_servers": list(g.dns_servers),
            "search_domains": list(g.search_domains),
            "gateway": str(net.network_address + g.gateway_offset),
            "expected_hosts": hosts,
        })
        y += 40 + g.host_count * 16 + 30

    y = 120
    for i, r in enumerate(topo.routers):
        nid = f"router-{i + 1}"
        router_ips = {}
        for gname in r.connects:
            gg = topo.group(gname)
            net = IPv4Network(gg.subnet, strict=False)
            router_ips[gname] = str(net.network_address + r.ip_suffix)
        nodes.append({
            "id": nid, "kind": "router", "x": 420, "y": y,
            "name": r.name, "ip_suffix": r.ip_suffix, "image": r.image,
            "expected_ips": router_ips,
        })
        for gname in r.connects:
            for node in nodes:
                if node["kind"] == "group" and node["name"] == gname:
                    edges.append({
                        "from": nid, "to": node["id"], "kind": "route",
                        "router_ip": router_ips.get(gname),
                    })
                    break
        y += 140

    y = 120
    for i, s in enumerate(topo.services):
        nid = f"service-{i + 1}"
        gg = topo.group(s.group)
        net = IPv4Network(gg.subnet, strict=False)
        nodes.append({
            "id": nid, "kind": "service", "x": 650, "y": y,
            "type": s.type, "group": s.group,
            "ip_suffix": s.ip_suffix, "upstream": s.upstream,
            "dhcp_range": list(s.dhcp_range),
            "expected_ip": str(net.network_address + s.ip_suffix),
        })
        y += 100

    return {"name": topo.name, "image": topo.image,
            "nodes": nodes, "edges": edges}


@router.post("/api/editor/preview")
def editor_preview(req: EditorTopology):
    try:
        topo = _editor_to_labtopology(req)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid topology: {exc}")
    preview = {"name": topo.name, "groups": [], "routers": [], "services": []}
    for g in topo.groups:
        net = IPv4Network(g.subnet, strict=False)
        hosts = [
            {"index": k,
             "ip": str(net.network_address + g.start_offset + (k - 1))}
            for k in range(1, g.host_count + 1)
        ]
        preview["groups"].append({
            "name": g.name, "subnet": g.subnet,
            "gateway": str(net.network_address + g.gateway_offset),
            "hosts": hosts, "type": g.topology.value,
        })
    for r in topo.routers:
        ips = {}
        for gname in r.connects:
            gg = topo.group(gname)
            net = IPv4Network(gg.subnet, strict=False)
            ips[gname] = str(net.network_address + r.ip_suffix)
        preview["routers"].append({
            "name": r.name, "connects": list(r.connects),
            "interfaces": ips,
        })
    for s in topo.services:
        gg = topo.group(s.group)
        net = IPv4Network(gg.subnet, strict=False)
        preview["services"].append({
            "type": s.type, "group": s.group,
            "ip": str(net.network_address + s.ip_suffix),
        })
    return preview


@router.post("/api/editor/save")
def editor_save(req: EditorTopology):
    try:
        topo = _editor_to_labtopology(req)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid topology: {exc}")
    from ..examples import save_topology
    safe = _safe_name(req.name)
    out_dir = Path.cwd() / "examples"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{safe}.yaml"
    try:
        save_topology(topo, str(path))
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))
    return {"ok": True, "path": str(path)}


@router.post("/api/editor/deploy")
def editor_deploy(req: EditorTopology):
    try:
        topo = _editor_to_labtopology(req)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid topology: {exc}")
    with _lock:
        try:
            Cluster(topo).deploy(allow_routing=True)
        except ConfigurationError as exc:
            raise HTTPException(409, detail=str(exc))
        except Exception as exc:
            raise HTTPException(500, detail=str(exc))
    _validation_cache.pop(topo.name, None)
    return {"ok": True, "cluster": topo.name}


@router.post("/api/editor/force-deploy")
def editor_force_deploy(req: EditorTopology):
    try:
        topo = _editor_to_labtopology(req)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid topology: {exc}")
    with _lock:
        removed_c, removed_n = _nuclear_cleanup()
        try:
            Cluster(topo).deploy(allow_routing=True)
        except ConfigurationError as exc:
            raise HTTPException(409, detail=(
                f"Cleanup removed {removed_c} containers, "
                f"{removed_n} networks. Deploy still failed: {exc}"
            ))
        except Exception as exc:
            raise HTTPException(500, detail=(
                f"Cleanup removed {removed_c} containers, "
                f"{removed_n} networks. Deploy failed: {exc}"
            ))
    _validation_cache.pop(topo.name, None)
    return {"ok": True, "cluster": topo.name,
            "cleanup": {"containers": removed_c, "networks": removed_n}}


# --- subnet calculator -----------------------------------------------------

@router.post("/api/subnet/analyze")
def subnet_analyze(req: dict):
    ip = (req.get("ip") or "").strip()
    subnet = (req.get("subnet") or "").strip() or None
    if not ip:
        raise HTTPException(400, detail="IP address required")
    try:
        if ":" in ip:
            return {"kind": "ipv6", "fields": _dc(analyze_ipv6(ip, subnet))}
        resolved = _resolve_subnet(ip, subnet)
        return {"kind": "ipv4", "fields": _dc(analyze_ipv4(ip, resolved))}
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


@router.post("/api/subnet/split")
def subnet_split(req: dict):
    subnet = (req.get("subnet") or "").strip()
    if not subnet:
        raise HTTPException(400, detail="subnet required")
    try:
        count = req.get("count")
        prefix = req.get("prefix")
        if count is not None:
            results = split_by_count(subnet, int(count))
        elif prefix is not None:
            results = split_subnet(subnet, int(prefix))
        else:
            raise HTTPException(400, detail="provide count or prefix")
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    return {"subnets": [
        {"network": str(s.network),
         "first_usable": s.first_usable,
         "last_usable": s.last_usable,
         "broadcast": s.broadcast_address,
         "usable_hosts": s.usable_hosts,
         "prefix": s.prefix_length,
         "netmask": s.netmask}
        for s in results
    ]}


# --- actions ---------------------------------------------------------------

@router.post("/api/deploy")
def deploy(req: dict):
    file = req.get("file")
    if not file:
        raise HTTPException(400, detail="file required")
    with _lock:
        try:
            topo = load_topology(file)
        except ConfigurationError as exc:
            raise HTTPException(400, detail=str(exc))
        try:
            Cluster(topo).deploy(allow_routing=True)
        except ConfigurationError as exc:
            raise HTTPException(409, detail=str(exc))
        except Exception as exc:
            raise HTTPException(500, detail=str(exc))
        _state["topology_file"] = file
        _state["topology"] = topo
    _validation_cache.pop(topo.name, None)
    return {"ok": True, "cluster": topo.name}


@router.post("/api/destroy")
def destroy():
    """Remove ALL netlab containers and networks — not just the active topology.

    This handles the case where the server lost its _state (restart) or
    the operator destroyed via CLI: the UI must be a reliable panic button.
    """
    with _lock:
        removed_c, removed_n = _nuclear_cleanup()
        _state["topology"] = None
        _state["topology_file"] = None
        _validation_cache.clear()
    return {
        "ok": True,
        "cleanup": {"containers": removed_c, "networks": removed_n},
    }


@router.post("/api/routing/enable")
def routing_enable():
    topo = _state.get("topology")
    if topo is None:
        raise HTTPException(400, detail="no active topology")
    fm = FirewallManager(topo)
    state = fm.install()
    return {"enabled": state.value == "0",
            "value": state.value, "hint": state.hint}


@router.post("/api/exec")
def exec_command(req: dict):
    host = req.get("host")
    command = req.get("command")
    if not host or not command:
        raise HTTPException(400, detail="host and command required")
    if not host.startswith("netlab-"):
        raise HTTPException(400, detail="invalid host name")
    try:
        c = docker.from_env().containers.get(host)
    except NotFound:
        raise HTTPException(404, detail="container not found")
    except APIError as exc:
        raise HTTPException(500, detail=str(exc))
    try:
        result = c.exec_run(["sh", "-c", command])
    except APIError as exc:
        raise HTTPException(500, detail=str(exc))
    return {"code": result.exit_code,
            "output": result.output.decode(errors="ignore")}


@router.post("/api/container/{name}/stop")
def container_stop(name: str):
    if not name.startswith("netlab-"):
        raise HTTPException(400, detail="invalid name")
    try:
        c = docker.from_env().containers.get(name)
        c.stop(timeout=3)
    except NotFound:
        raise HTTPException(404, detail="not found")
    except APIError as exc:
        raise HTTPException(500, detail=str(exc))
    return {"ok": True}


@router.post("/api/container/{name}/start")
def container_start(name: str):
    if not name.startswith("netlab-"):
        raise HTTPException(400, detail="invalid name")
    try:
        c = docker.from_env().containers.get(name)
        c.start()
    except NotFound:
        raise HTTPException(404, detail="not found")
    except APIError as exc:
        raise HTTPException(500, detail=str(exc))
    return {"ok": True}


@router.post("/api/container/{name}/logs")
def container_logs(name: str):
    if not name.startswith("netlab-"):
        raise HTTPException(400, detail="invalid name")
    try:
        c = docker.from_env().containers.get(name)
        logs = c.logs(tail=50).decode(errors="ignore")
    except NotFound:
        raise HTTPException(404, detail="not found")
    except APIError as exc:
        raise HTTPException(500, detail=str(exc))
    return {"output": logs}


@router.post("/api/doctor")
def doctor(req: dict):
    fix = bool(req.get("fix"))
    file = req.get("file")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if fix:
            topo = None
            if file:
                try:
                    topo = load_topology(file)
                except ConfigurationError as exc:
                    return {"ok": False, "output": str(exc)}
            run_fixes(topo)
        else:
            run_checks()
    return {"ok": True, "output": buf.getvalue()}