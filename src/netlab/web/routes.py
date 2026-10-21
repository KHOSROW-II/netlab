"""HTTP routes for the NetLab web UI."""
import contextlib
import io
import re
import threading
import tempfile
from ipaddress import IPv4Network
from pathlib import Path
from typing import Optional

import docker
from docker.errors import APIError, NotFound
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .. import __version__
from ..cluster import Cluster
from ..doctor import run_checks, run_fixes
from ..exceptions import ConfigurationError
from ..firewall import FirewallManager
from ..ipam import analyze_ipv4, split_by_count
from ..topology import GroupSpec, LabTopology, RouterSpec, ServiceSpec, TopologyType, load_topology

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter()

_lock = threading.Lock()
_state: dict = {"topology_file": None, "topology": None}
_active_traffic: dict = {}


def _discover_topologies() -> list[dict]:
    results, seen = [], set()
    for pattern in ("examples/*.yaml", "*.yaml"):
        for p in sorted(Path.cwd().glob(pattern)):
            if p.resolve() not in seen:
                seen.add(p.resolve())
                results.append({"path": str(p), "name": p.stem})
    return results


def _get_containers(topology_name: Optional[str]):
    try:
        client = docker.from_env()
        filters = {"label": f"netlab={topology_name}"} if topology_name else {"label": "netlab"}
        return client.containers.list(all=True, filters=filters)
    except Exception:
        return []


def _nuclear_cleanup() -> tuple[int, int]:
    cr = nr = 0
    try:
        client = docker.from_env()
        for c in client.containers.list(all=True, filters={"label": "netlab"}):
            try: c.remove(force=True); cr += 1
            except Exception: pass
        for net in client.networks.list():
            if net.name.startswith("netlab-"):
                try: net.remove(); nr += 1
                except Exception: pass
    except Exception: pass
    return cr, nr


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"version": __version__, "topologies": _discover_topologies()}
    )


@router.get("/api/status")
def get_status():
    topo = _state.get("topology")
    name = topo.name if topo else None
    containers = _get_containers(name)
    groups, routers, services, placeholders = {}, [], [], []
    
    for c in containers:
        role = c.labels.get("netlab.role", "host")
        group = c.labels.get("netlab.group")
        ips = {n: d.get("IPAddress", "") for n, d in c.attrs.get("NetworkSettings", {}).get("Networks", {}).items() if d.get("IPAddress")}
        d = {"name": c.name, "label": c.name.replace("netlab-", ""), "role": role, "group": group, "service": c.labels.get("netlab.service"), "status": c.status, "ips": ips}
        if role == "router": routers.append(d)
        elif role == "service": services.append(d)
        elif role in ("switch", "hub", "ap", "modem"): placeholders.append(d)
        elif group: groups.setdefault(group, []).append(d)

    return {
        "cluster": name or "(none)",
        "groups": [{"name": g, "containers": sorted(cs, key=lambda c: c["name"])} for g, cs in sorted(groups.items())],
        "routers": sorted(routers, key=lambda c: c["name"]),
        "services": sorted(services, key=lambda c: c["name"]),
        "placeholders": sorted(placeholders, key=lambda c: c["name"])
    }


@router.get("/api/graph")
def graph():
    topo = _state.get("topology")
    topo_name = topo.name if topo else None
    containers = _get_containers(topo_name)
    
    if not containers:
        _state["topology"] = None
        return {"cluster": "(none)", "nodes": [], "edges": [], "networks": [], "groups": []}

    if not topo_name:
        names = {c.labels.get("netlab") for c in containers if c.labels.get("netlab")}
        if len(names) == 1:
            topo_name = names.pop()

    client = docker.from_env()
    real_nets = {}
    nets_filter = {"label": f"netlab={topo_name}"} if topo_name else {"label": "netlab"}
    try:
        for net in client.networks.list(filters=nets_filter):
            cfg = (net.attrs.get("IPAM", {}).get("Config") or [{}])[0]
            real_nets[net.name] = {"name": net.name, "subnet": cfg.get("Subnet"), "gateway": cfg.get("Gateway")}
    except Exception:
        pass

    nodes = []
    for c in containers:
        ips = {n: d.get("IPAddress", "") for n, d in c.attrs.get("NetworkSettings", {}).get("Networks", {}).items() if d.get("IPAddress")}
        nodes.append({"name": c.name, "label": c.name.replace("netlab-", ""), "role": c.labels.get("netlab.role", "host"), "group": c.labels.get("netlab.group"), "status": c.status, "ips": ips})

    edges = []
    for net_name, meta in real_nets.items():
        on_net = [n for n in nodes if net_name in n["ips"]]
        if len(on_net) >= 2:
            central = next((n for n in on_net if n["role"] in ("switch", "hub", "ap", "modem")), None)
            if central:
                for n in on_net:
                    if n["name"] != central["name"]: edges.append({"source": n["name"], "target": central["name"], "network": net_name})
            else:
                for i in range(len(on_net)):
                    for j in range(i+1, len(on_net)):
                        edges.append({"source": on_net[i]["name"], "target": on_net[j]["name"], "network": net_name})

    groups_meta = []
    if topo:
        groups_meta = [{"name": g.name, "subnet": g.subnet, "type": g.topology.value} for g in topo.groups]
    else:
        inferred_groups = set(c.labels.get("netlab.group") for c in containers if c.labels.get("netlab.group"))
        for g_name in inferred_groups:
            groups_meta.append({"name": g_name, "subnet": "unknown", "type": "unknown"})

    return {"cluster": topo_name or "(none)", "nodes": nodes, "edges": edges, "networks": list(real_nets.values()), "groups": groups_meta}


# --- Calculator API (Fixes the 404) ---
@router.post("/api/subnet/analyze")
def subnet_analyze(req: dict):
    ip, subnet = req.get("ip", "").strip(), req.get("subnet", "").strip() or None
    if not ip: raise HTTPException(400, detail="IP required")
    try:
        info = analyze_ipv4(ip, subnet)
        return {"kind": "ipv4", "fields": {
            "address": info.address, "subnet": info.subnet, "class": info.ip_class.value if info.ip_class else "",
            "prefix": info.prefix_length, "netmask": info.netmask, "network": info.network_address,
            "broadcast": info.broadcast_address, "first": info.first_usable, "last": info.last_usable,
            "hosts": info.usable_hosts, "binary": info.binary_address
        }}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


# --- Traffic APIs ---
@router.post("/api/traffic/start")
def start_traffic(req: dict):
    source, target = req.get("source"), req.get("target")
    if not source or not target: raise HTTPException(400, "source and target required")
    
    client = docker.from_env()
    try:
        src_c = client.containers.get(source)
        tgt_c = client.containers.get(target)
    except NotFound: raise HTTPException(404, "Container not found")
    
    target_ips = [d.get('IPAddress') for d in tgt_c.attrs['NetworkSettings']['Networks'].values() if d.get('IPAddress')]
    if not target_ips: raise HTTPException(400, "Target has no IP")
    target_ip = target_ips[0]
    
    tgt_c.exec_run(["sh", "-c", "pkill iperf3; iperf3 -s -D"])
    src_c.exec_run(["sh", "-c", f"pkill iperf3; iperf3 -c {target_ip} -t 3600 -P 2 > /dev/null 2>&1 &"])
    
    _active_traffic[source] = target_ip
    return {"ok": True}

@router.post("/api/traffic/start_global")
def start_global_traffic():
    topo = _state.get("topology")
    if not topo: raise HTTPException(400, "No active topology")
    client = docker.from_env()
    
    for group in topo.groups:
        gw_ip = str(IPv4Network(group.subnet).network_address + 1)
        for i in range(1, group.host_count + 1):
            h_name = f"netlab-{group.name}-host{i}"
            try:
                c = client.containers.get(h_name)
                c.exec_run(["sh", "-c", f"ping -i 0.5 {gw_ip} > /dev/null 2>&1 &"])
                _active_traffic[h_name] = gw_ip
            except: pass
    return {"ok": True}

@router.post("/api/traffic/stop_all")
def stop_all_traffic():
    client = docker.from_env()
    for source in list(_active_traffic.keys()):
        try:
            c = client.containers.get(source)
            c.exec_run(["pkill", "iperf3"])
            c.exec_run(["pkill", "ping"])
        except: pass
    _active_traffic.clear()
    return {"ok": True}

@router.get("/api/traffic/status")
def get_traffic_status():
    return {"active": _active_traffic}

@router.post("/api/container/{name}/bandwidth")
def set_bandwidth(name: str, req: dict):
    limit = req.get("limit", 0)
    client = docker.from_env()
    try:
        c = client.containers.get(name)
        c.exec_run(["sh", "-c", "for i in eth1 eth2 eth3; do tc qdisc del dev $i root 2>/dev/null || true; done"])
        if limit > 0:
            cmd = f"for i in eth1 eth2 eth3; do tc qdisc add dev $i root tbf rate {limit}mbit burst 32kbit latency 400ms 2>/dev/null || true; done"
            c.exec_run(["sh", "-c", cmd])
            return {"ok": True, "msg": f"Bandwidth limited to {limit} Mbps"}
        return {"ok": True, "msg": "Bandwidth unlimited"}
    except NotFound:
        raise HTTPException(404, "Container not found")


# --- Editor APIs ---
@router.post("/api/editor/load")
def editor_load(body: dict):
    path = body.get("path")
    if not path: raise HTTPException(400, detail="path required")
    try: topo = load_topology(path)
    except ConfigurationError as exc: raise HTTPException(400, detail=str(exc))

    nodes, edges, y = [], [], 100
    for i, g in enumerate(topo.groups):
        nodes.append({"id": f"group-{i+1}", "type": g.topology.value, "x": 150, "y": y, "name": g.name, "subnet": g.subnet, "host_count": g.host_count})
        y += 100
    for i, r in enumerate(topo.routers):
        nodes.append({"id": f"router-{i+1}", "type": "router", "x": 450, "y": 200 + i*100, "name": r.name, "subnet": None})
        for g in topo.groups:
            if g.name in r.connects:
                target = next((n for n in nodes if n["name"] == g.name), None)
                if target: edges.append({"from": f"router-{i+1}", "to": target["id"]})
    return {"name": topo.name, "nodes": nodes, "edges": edges}

@router.post("/api/editor/calculate")
def editor_calculate(req: dict):
    nodes, edges = req.get("nodes", []), req.get("edges", [])
    subnets_seen = []
    for n in nodes:
        if n["type"] in ["switch", "hub", "access_point", "modem"]:
            try:
                net = IPv4Network(n.get("subnet", "192.168.1.0/24"), strict=False)
                for s in subnets_seen:
                    if net.overlaps(s): raise ValueError(f"Subnet {net} overlaps!")
                subnets_seen.append(net)
                n["resolved_network"] = str(net.network_address)
                n["resolved_mask"] = str(net.netmask)
                n["resolved_gateway"] = str(net.network_address + 1)
            except Exception as e: raise HTTPException(400, detail=str(e))

    pc_counter = {}
    for n in nodes:
        if n["type"] == "pc":
            parent_edge = next((e for e in edges if e["from"] == n["id"] or e["to"] == n["id"]), None)
            if parent_edge:
                parent_id = parent_edge["to"] if parent_edge["from"] == n["id"] else parent_edge["from"]
                parent = next((x for x in nodes if x["id"] == parent_id), None)
                if parent and parent.get("resolved_network"):
                    base = int(IPv4Network(parent["subnet"]).network_address)
                    count = pc_counter.get(parent["id"], 0)
                    pc_counter[parent["id"]] = count + 1
                    n["resolved_ip"] = str(base + 10 + count)
    return {"nodes": nodes, "edges": edges}

@router.post("/api/editor/deploy")
def editor_deploy(req: dict):
    groups = [GroupSpec(name=g["name"], subnet=g["subnet"], host_count=g.get("host_count", 1), topology=TopologyType(g["topology"])) for g in req.get("groups", [])]
    routers = [RouterSpec(name=r["name"], connects=tuple(r["connects"]), ip_suffix=254) for r in req.get("routers", [])]
    topo = LabTopology(name=req.get("name", "editor"), groups=groups, routers=routers, services=[])
    try: topo.validate()
    except ConfigurationError as exc: raise HTTPException(400, detail=str(exc))

    with _lock:
        try: Cluster(topo).deploy(allow_routing=True)
        except Exception as exc: raise HTTPException(500, detail=str(exc))
        _state["topology"] = topo
    return {"ok": True, "cluster": topo.name}


@router.post("/api/destroy")
def destroy():
    with _lock:
        _nuclear_cleanup()
        _state["topology"] = None
    return {"ok": True}

@router.post("/api/exec")
def exec_command(req: dict):
    try:
        c = docker.from_env().containers.get(req.get("host"))
        r = c.exec_run(["sh", "-c", req.get("command", "ls")])
        return {"code": r.exit_code, "output": r.output.decode(errors="ignore")}
    except Exception as e: raise HTTPException(500, detail=str(e))

@router.post("/api/doctor")
def doctor(req: dict):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if req.get("fix"): run_fixes()
        else: run_checks()
    return {"ok": True, "output": buf.getvalue()}

@router.post("/api/routing/enable")
def routing_enable():
    topo = _state.get("topology")
    if not topo:
        raise HTTPException(400, detail="Deploy a topology first.")
    fm = FirewallManager(topo)
    state = fm.install()
    if state.value != "0":
        raise HTTPException(403, detail=f"Failed to disable br_netfilter. Are you running as root? Hint: {state.hint}")
    return {"ok": True}