"""Command line interface for NetLab."""
import argparse
import logging
import sys

from .animate import animate_events
from .cluster import Cluster
from .config import LabConfig
from .doctor import run_checks
from .examples import write_example
from .exceptions import ConfigurationError, NetLabError
from .ipam import (
    HostIPPlanner,
    analyze_ipv4,
    analyze_ipv6,
    split_by_count,
    split_subnet,
)
from .lab import Lab
from .protocols import (
    ARPLive,
    ARPSimulator,
    DHCPSimulator,
    DNSLive,
    DNSSimulator,
    ICMPLive,
    ICMPSimulator,
    render_summary,
    render_timeline,
)
from .topology import load_topology
from .viz import build_graph, render_ascii, to_dot
from .viz.render import render_image
from .firewall import FirewallManager
from .doctor import run_checks, run_fixes
from .watcher import ClusterWatcher

logger = logging.getLogger(__name__)


# --- Phase 1 deploy -----------------------------------------------------------

def _build_deploy_parser():
    p = argparse.ArgumentParser(prog="netlab",
                                description="NetLab - deploy a simulation")
    p.add_argument("-n", "--hosts", type=int, default=5, dest="host_count")
    p.add_argument("--subnet", default="10.10.0.0/24")
    p.add_argument("--network-name", default="netlab-p1")
    p.add_argument("--image", default="nicolaka/netshoot:latest")
    p.add_argument("--start-ip-offset", type=int, default=10)
    p.add_argument("--cleanup", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _run_deploy(argv):
    args = _build_deploy_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.check:
        return run_checks()
    config = LabConfig(
        host_count=args.host_count, subnet=args.subnet,
        network_name=args.network_name, image=args.image,
        start_ip_offset=args.start_ip_offset,
    )
    try:
        lab = Lab(config)
        if args.cleanup:
            lab.destroy()
            logger.info("Cleanup completed")
        else:
            lab.deploy()
            lab.run_connectivity_check()
            lab.print_summary()
    except NetLabError as exc:
        logger.error("%s", exc); return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted"); return 130
    return 0


# --- Phase 2 ipam -------------------------------------------------------------

def _cmd_analyze(args):
    if ":" in args.address:
        info = analyze_ipv6(args.address, args.subnet)
        print("IPv6 Address Analysis"); print("=" * 55)
        print(f"Address        : {info.address}")
        print(f"Subnet         : {info.subnet}")
        print(f"Prefix length  : /{info.prefix_length}")
        print(f"Host bits      : {info.host_bits_count}")
        print(f"Hex            : {info.hex_address}")
        print(f"Network        : {info.network_address}")
        print(f"Last address   : {info.last_address}")
        if info.interface_id:
            print(f"Interface ID   : {info.interface_id}")
        if not info.address_in_subnet:
            print("Warning        : address not in subnet")
    else:
        info = analyze_ipv4(args.address, args.subnet)
        print("IPv4 Address Analysis"); print("=" * 55)
        print(f"Address        : {info.address}")
        print(f"Subnet         : {info.subnet}")
        if info.ip_class is not None:
            print(f"Class          : {info.ip_class.value}")
        print(f"Prefix length  : /{info.prefix_length}")
        print(f"Netmask        : {info.netmask}")
        print(f"Host bits      : {info.host_bits_count}")
        print(); print("Binary breakdown:")
        print(f"  Address      : {info.binary_address}")
        print(f"  Netmask      : {info.binary_netmask}")
        print(f"  Network bits : {info.network_bits}")
        print(f"  Host bits    : {info.host_bits}")
        print(f"  Network      : {info.binary_network}")
        print(f"  Broadcast    : {info.binary_broadcast}")
        print(); print("Subnet details:")
        print(f"  Network         : {info.network_address}")
        print(f"  Broadcast       : {info.broadcast_address}")
        print(f"  First usable    : {info.first_usable}")
        print(f"  Last usable     : {info.last_usable}")
        print(f"  Total addresses : {info.total_addresses}")
        print(f"  Usable hosts    : {info.usable_hosts}")
        if not info.address_in_subnet:
            print("  Warning         : address not in subnet")
    return 0


def _cmd_split(args):
    subnets = (
        split_by_count(args.subnet, args.count) if args.count is not None
        else split_subnet(args.subnet, args.prefix)
    )
    parent = subnets[0].network
    print("Subnet Split"); print("=" * 70)
    print(f"Parent         : {args.subnet}")
    print(f"New prefix     : /{parent.prefixlen}")
    print(f"Subnets        : {len(subnets)}"); print()
    for idx, s in enumerate(subnets, start=1):
        print(f"  #{idx:<3} {s.network!s:<18} "
              f"{s.first_usable:<15} - {s.last_usable:<15} "
              f"({s.usable_hosts} hosts)")
    return 0


def _cmd_plan(args):
    planner = HostIPPlanner(
        cidr=args.subnet, start_offset=args.start_offset,
        gateway_offset=args.gateway_offset,
    )
    assignments = planner.plan(args.host_count)
    print("Host IP Plan"); print("=" * 55)
    print(f"Subnet         : {args.subnet}")
    print(f"Gateway        : {planner.gateway}")
    print(f"Start offset   : {args.start_offset}")
    print(f"Hosts          : {len(assignments)}"); print()
    for a in assignments:
        print(f"  #{a.index:<3} {a.address}")
    return 0


def _build_ipam_parser():
    p = argparse.ArgumentParser(prog="netlab ipam")
    sub = p.add_subparsers(dest="ipam_command", required=True)
    x = sub.add_parser("analyze"); x.add_argument("address")
    x.add_argument("--subnet", default=None); x.set_defaults(func=_cmd_analyze)
    x = sub.add_parser("split"); x.add_argument("subnet")
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--count", type=int); g.add_argument("--prefix", type=int)
    x.set_defaults(func=_cmd_split)
    x = sub.add_parser("plan"); x.add_argument("subnet")
    x.add_argument("-n", "--hosts", type=int, default=5, dest="host_count")
    x.add_argument("--start-offset", type=int, default=10)
    x.add_argument("--gateway-offset", type=int, default=1)
    x.set_defaults(func=_cmd_plan)
    return p


def _run_ipam(argv):
    args = _build_ipam_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, ConfigurationError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1


# --- Phase 3 cluster ----------------------------------------------------------

def _cmd_cluster_up(args):
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    Cluster(load_topology(args.file)).deploy(
        allow_routing=getattr(args, "allow_routing", False)
    )
    print(f"Cluster deployed from {args.file}")
    return 0


def _cmd_cluster_firewall_install(args):
    topo = load_topology(args.file)
    state = Cluster(topo).firewall_install()
    if not state.needs_change:
        print(f"OK: br_netfilter already disabled (value={state.value}).")
        return 0
    if state.can_change:
        # already changed by install()
        if state.value == "0":
            print("OK: br_netfilter disabled; cross-group routing enabled.")
            return 0
        print(f"Failed: sysctl value still {state.value}.")
        return 1
    print("This process is not root. Run these commands:")
    for cmd in FirewallManager(topo).persist_commands():
        print(f"  {cmd}")
    return 1


def _cmd_cluster_firewall_status(args):
    Cluster(load_topology(args.file)).firewall_status()
    return 0


def _cmd_cluster_firewall_revoke(args):
    topo = load_topology(args.file)
    state = Cluster(topo).firewall_revoke()
    if state.value != "0":
        print("Cannot change (not root). Run:")
        print(f"  sudo sysctl -w net.bridge.bridge-nf-call-iptables=1")
        return 1
    print("br_netfilter re-enabled. Docker isolation restored.")
    return 0


def _cmd_cluster_firewall_allow(args):
    topo = load_topology(args.file)
    fm = FirewallManager(topo)
    if not fm.required_rules():
        print("No routers defined; no inter-bridge rules required.")
        return 0
    print("Required DOCKER-USER rules:")
    for src, dst in fm.required_rules():
        print(f"  {src}  ->  {dst}  ACCEPT")
    print()
    applied, failed = fm.apply()
    if applied and not failed:
        print(f"OK: {applied} rule(s) applied.")
        return 0
    if applied and failed:
        print(f"Partial: {applied} applied, {failed} failed.")
    if not applied:
        print("Could not apply rules directly (need root). "
              "Run these with sudo:")
        for cmd in fm.build_commands():
            print(f"  {cmd}")
    return 0 if failed == 0 else 1


def _cmd_cluster_firewall_revoke(args):
    topo = load_topology(args.file)
    fm = FirewallManager(topo)
    removed, failed = fm.remove()
    if removed and not failed:
        print(f"OK: {removed} rule(s) removed.")
        return 0
    if not removed:
        print("Could not remove rules (need root). Run these with sudo:")
        for cmd in fm.build_remove_commands():
            print(f"  {cmd}")
    return 0 if failed == 0 else 1


def _cmd_cluster_down(args):
    Cluster(load_topology(args.file)).destroy()
    print(f"Cluster destroyed: {args.file}")
    return 0


def _cmd_cluster_status(args):
    Cluster(load_topology(args.file)).status()
    return 0


def _cmd_cluster_exec(args):
    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("Error: no command provided", file=sys.stderr); return 1
    return Cluster(load_topology(args.file)).exec(args.group, args.host, cmd)


def _cmd_cluster_set_dns(args):
    Cluster(load_topology(args.file)).set_dns(
        args.group, args.host, args.servers, args.search or None
    )
    return 0


def _cmd_cluster_set_ip(args):
    Cluster(load_topology(args.file)).set_ip(args.group, args.host, args.ip)
    return 0


def _cmd_cluster_diagnose(args):
    """Print routes, forwarding, and live connectivity for every container."""
    topo = load_topology(args.file)
    import docker as _docker
    import ipaddress
    client = _docker.from_env()

    for spec in topo.groups:
        if spec.topology.value == "ring":
            continue
        for idx in range(1, spec.host_count + 1):
            name = f"netlab-{spec.name}-host{idx}"
            try:
                c = client.containers.get(name)
            except _docker.errors.NotFound:
                print(f"\n[{name}] MISSING"); continue
            print(f"\n=== {name} ===")
            print("forwarding:",
                  c.exec_run(["sysctl", "-n", "net.ipv4.ip_forward"])
                    .output.decode().strip())
            print("routes:")
            print(c.exec_run(["ip", "route"]).output.decode().rstrip())

    for r in topo.routers:
        name = f"netlab-{r.name}"
        try:
            c = client.containers.get(name)
        except _docker.errors.NotFound:
            print(f"\n[{name}] MISSING"); continue
        print(f"\n=== {name} ===")
        print("forwarding:",
              c.exec_run(["sysctl", "-n", "net.ipv4.ip_forward"])
                .output.decode().strip())
        print("routes:")
        print(c.exec_run(["ip", "route"]).output.decode().rstrip())

    for svc in topo.services:
        name = f"netlab-{svc.group}-dnsmasq"
        try:
            c = client.containers.get(name)
        except _docker.errors.NotFound:
            print(f"\n[{name}] MISSING"); continue
        print(f"\n=== {name} ===")
        print("status:", c.status)
        print("logs (tail 5):")
        try:
            print(c.logs(tail=5).decode(errors="ignore").rstrip())
        except Exception as exc:
            print(f"  (could not read logs: {exc})")

    if topo.routers:
        r = topo.routers[0]
        if len(r.connects) >= 2:
            src = topo.group(r.connects[0])
            dst = topo.group(r.connects[1])
            dst_net = ipaddress.IPv4Network(dst.subnet, strict=False)
            dst_ip = str(dst_net.network_address + dst.start_offset)
            src_name = f"netlab-{src.name}-host1"
            try:
                c = client.containers.get(src_name)
                print(f"\n=== ping from {src_name} to {dst_ip} ===")
                print(c.exec_run(["ping", "-c", "2", "-W", "2", dst_ip])
                        .output.decode().rstrip())
            except _docker.errors.NotFound:
                print(f"\n[{src_name}] MISSING")
    return 0

# --- Day 2: doctor + watch ----------------------------------------------------

def _cmd_doctor(args):
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    topology = None
    if args.file:
        topology = load_topology(args.file)
    if args.fix:
        return run_fixes(topology)
    return run_checks()


def _build_doctor_parser():
    p = argparse.ArgumentParser(prog="netlab doctor")
    p.add_argument("-f", "--file", default=None,
                   help="topology YAML (needed for --fix on cluster resources)")
    p.add_argument("--fix", action="store_true",
                   help="attempt to repair common problems")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=_cmd_doctor)
    return p


def _cmd_cluster_watch(args):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    topo = load_topology(args.file)
    ClusterWatcher(
        topo, interval=args.interval, max_restarts=args.max_restarts,
    ).run()
    return 0

def _build_cluster_parser():
    p = argparse.ArgumentParser(prog="netlab cluster")
    sub = p.add_subparsers(dest="cluster_command", required=True)

    x = sub.add_parser("up")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("--allow-routing", action="store_true")
    x.add_argument("-v", "--verbose", action="store_true")
    x.set_defaults(func=_cmd_cluster_up)

    x = sub.add_parser("down")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_cluster_down)

    x = sub.add_parser("status")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_cluster_status)

    x = sub.add_parser("diagnose")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_cluster_diagnose)

    x = sub.add_parser("exec")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("-i", "--host", default="all")
    x.add_argument("command", nargs=argparse.REMAINDER)
    x.set_defaults(func=_cmd_cluster_exec)

    x = sub.add_parser("set-dns")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("-i", "--host", default="all")
    x.add_argument("--server", action="append", required=True, dest="servers")
    x.add_argument("--search", action="append", default=[], dest="search")
    x.set_defaults(func=_cmd_cluster_set_dns)

    x = sub.add_parser("set-ip")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("-i", "--host", type=int, required=True)
    x.add_argument("--ip", required=True)
    x.set_defaults(func=_cmd_cluster_set_ip)

    x = sub.add_parser("watch")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("--interval", type=int, default=5)
    x.add_argument("--max-restarts", type=int, default=3,
                   dest="max_restarts")
    x.set_defaults(func=_cmd_cluster_watch)

    x = sub.add_parser("firewall-install")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_cluster_firewall_install)

    x = sub.add_parser("firewall-status")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_cluster_firewall_status)

    x = sub.add_parser("firewall-revoke")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_cluster_firewall_revoke)

    return p


def _run_cluster(argv):
    args = _build_cluster_parser().parse_args(argv)
    try:
        return args.func(args)
    except (NetLabError, ConfigurationError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1


# --- Phase 4 viz --------------------------------------------------------------

def _cmd_viz_ascii(args):
    topo = load_topology(args.file)
    print(render_ascii(topo, args.group)); return 0


def _cmd_viz_dot(args):
    topo = load_topology(args.file)
    text = to_dot(topo)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"DOT written to {args.output}")
    else:
        print(text)
    return 0


def _cmd_viz_render(args):
    topo = load_topology(args.file)
    render_image(topo, args.output, args.group)
    print(f"Image written to {args.output}"); return 0


def _cmd_viz_summary(args):
    topo = load_topology(args.file)
    graph = build_graph(topo)
    by_kind: dict[str, int] = {}
    for _, data in graph.nodes(data=True):
        kind = data.get("kind", "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    print(f"Cluster : {topo.name}")
    print(f"Nodes   : {graph.number_of_nodes()}")
    print(f"Edges   : {graph.number_of_edges()}")
    print(f"Types   : {by_kind}")
    for spec in topo.groups:
        print(f"  group {spec.name}: {spec.topology.value}, "
              f"{spec.host_count} hosts, {spec.subnet}")
    if topo.routers:
        for r in topo.routers:
            print(f"  router {r.name}: connects {','.join(r.connects)}")
    if topo.services:
        for s in topo.services:
            print(f"  service {s.type} on {s.group}")
    return 0


def _build_viz_parser():
    p = argparse.ArgumentParser(prog="netlab viz")
    sub = p.add_subparsers(dest="viz_command", required=True)
    x = sub.add_parser("ascii")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", default=None)
    x.set_defaults(func=_cmd_viz_ascii)
    x = sub.add_parser("dot")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-o", "--output", default=None)
    x.set_defaults(func=_cmd_viz_dot)
    x = sub.add_parser("render")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-o", "--output", required=True)
    x.add_argument("-g", "--group", default=None)
    x.set_defaults(func=_cmd_viz_render)
    x = sub.add_parser("summary")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_viz_summary)
    return p


def _run_viz(argv):
    args = _build_viz_parser().parse_args(argv)
    try:
        return args.func(args)
    except (NetLabError, ConfigurationError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1


# --- Phase 3 example ----------------------------------------------------------

def _cmd_example(args):
    write_example(args.output)
    print(f"Example topology written to {args.output}")
    return 0


def _build_example_parser():
    p = argparse.ArgumentParser(prog="netlab example")
    p.add_argument("-o", "--output", default="phase3-topology.yaml")
    p.set_defaults(func=_cmd_example)
    return p


def _run_example(argv):
    args = _build_example_parser().parse_args(argv)
    try:
        return args.func(args)
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1


# --- Phase 5 protocol ---------------------------------------------------------

def _resolve_dst_ip(topo, group_name, host_idx):
    spec = topo.group(group_name)
    planner = HostIPPlanner(
        cidr=spec.subnet, start_offset=spec.start_offset,
        gateway_offset=spec.gateway_offset,
    )
    return planner.plan(host_idx)[-1].address


def _emit_events(events, title, animate: bool, delay_ms: int):
    if animate:
        animate_events(events, delay_ms=delay_ms, color=True, title=title)
    else:
        print(render_timeline(events, title))
    print()
    print(render_summary(events))


def _cmd_protocol_arp(args):
    topo = load_topology(args.file)
    dst_ip = _resolve_dst_ip(topo, args.group, args.to)
    try:
        if args.mode == "simulated":
            events = ARPSimulator(topo, args.group, args.src, args.to).run()
        else:
            events = ARPLive(args.group, args.src, dst_ip).run()
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1
    _emit_events(events, f"ARP - group {args.group} ({args.mode})",
                 args.animate, args.delay)
    return 0


def _cmd_protocol_icmp(args):
    topo = load_topology(args.file)
    dst_ip = _resolve_dst_ip(topo, args.group, args.to)
    try:
        if args.mode == "simulated":
            events = ICMPSimulator(topo, args.group, args.src, args.to).run()
        else:
            events = ICMPLive(args.group, args.src, dst_ip, args.count).run()
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1
    _emit_events(events, f"ICMP - group {args.group} ({args.mode})",
                 args.animate, args.delay)
    return 0


def _cmd_protocol_dns(args):
    topo = load_topology(args.file)
    try:
        if args.mode == "simulated":
            events = DNSSimulator(
                topo, args.group, args.src,
                query=args.query, server=args.server,
            ).run()
        else:
            events = DNSLive(
                args.group, args.src, args.query, args.server
            ).run()
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1
    _emit_events(events, f"DNS - group {args.group} ({args.mode})",
                 args.animate, args.delay)
    return 0


def _cmd_protocol_dhcp(args):
    topo = load_topology(args.file)
    events = DHCPSimulator(topo, args.group, args.src).run()
    _emit_events(events, f"DHCP - group {args.group} (simulated)",
                 args.animate, args.delay)
    return 0


def _cmd_protocol_demo(args):
    topo = load_topology(args.file)
    specs = [
        ("ARP", lambda: ARPSimulator(topo, args.group, 1, 2).run()),
        ("ICMP", lambda: ICMPSimulator(topo, args.group, 1, 2).run()),
        ("DNS", lambda: DNSSimulator(topo, args.group, 1,
                                     query="example.com").run()),
        ("DHCP", lambda: DHCPSimulator(topo, args.group, 1).run()),
    ]
    for name, run in specs:
        print()
        _emit_events(run(), f"=== {name} ===", args.animate, args.delay)
    return 0


def _add_animate_flags(p):
    p.add_argument("--animate", action="store_true",
                   help="render events as a timed, colored animation")
    p.add_argument("--delay", type=int, default=400,
                   help="delay in ms between animated events (default: 400)")


def _build_protocol_parser():
    p = argparse.ArgumentParser(prog="netlab protocol")
    sub = p.add_subparsers(dest="protocol_command", required=True)

    x = sub.add_parser("arp")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("--from", dest="src", type=int, default=1)
    x.add_argument("--to", type=int, default=2)
    x.add_argument("--mode", choices=["simulated", "live"], default="simulated")
    _add_animate_flags(x)
    x.set_defaults(func=_cmd_protocol_arp)

    x = sub.add_parser("icmp")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("--from", dest="src", type=int, default=1)
    x.add_argument("--to", type=int, default=2)
    x.add_argument("--count", type=int, default=4)
    x.add_argument("--mode", choices=["simulated", "live"], default="simulated")
    _add_animate_flags(x)
    x.set_defaults(func=_cmd_protocol_icmp)

    x = sub.add_parser("dns")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("--from", dest="src", type=int, default=1)
    x.add_argument("--query", required=True)
    x.add_argument("--server", default="8.8.8.8")
    x.add_argument("--mode", choices=["simulated", "live"], default="simulated")
    _add_animate_flags(x)
    x.set_defaults(func=_cmd_protocol_dns)

    x = sub.add_parser("dhcp")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("--from", dest="src", type=int, default=1)
    _add_animate_flags(x)
    x.set_defaults(func=_cmd_protocol_dhcp)

    x = sub.add_parser("demo")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    _add_animate_flags(x)
    x.set_defaults(func=_cmd_protocol_demo)
    return p


def _run_protocol(argv):
    args = _build_protocol_parser().parse_args(argv)
    try:
        return args.func(args)
    except (NetLabError, ConfigurationError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1


# --- Phase 6 router/service ---------------------------------------------------

def _cmd_router_list(args):
    topo = load_topology(args.file)
    if not topo.routers:
        print("No routers defined in this topology.")
        return 0
    print(f"Routers in {args.file}:")
    for r in topo.routers:
        print(f"  {r.name:<12} connects={','.join(r.connects)} "
              f"ip_suffix={r.ip_suffix}")
    return 0


def _cmd_router_add(args):
    topo = load_topology(args.file)
    from .topology import RouterSpec
    new = RouterSpec(
        name=args.name,
        connects=tuple(args.connects.split(",")),
        ip_suffix=args.ip_suffix,
    )
    new.validate()
    existing = {r.name for r in topo.routers}
    if new.name in existing:
        print(f"Error: router '{new.name}' already exists", file=sys.stderr)
        return 1
    topo.routers.append(new)
    from .examples import save_topology
    save_topology(topo, args.file)
    print(f"Router '{new.name}' added to {args.file}")
    return 0


def _cmd_router_remove(args):
    topo = load_topology(args.file)
    before = len(topo.routers)
    topo.routers = [r for r in topo.routers if r.name != args.name]
    if len(topo.routers) == before:
        print(f"Error: router '{args.name}' not found", file=sys.stderr)
        return 1
    from .examples import save_topology
    save_topology(topo, args.file)
    print(f"Router '{args.name}' removed from {args.file}")
    return 0


def _build_router_parser():
    p = argparse.ArgumentParser(prog="netlab router")
    sub = p.add_subparsers(dest="router_command", required=True)
    x = sub.add_parser("list")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_router_list)
    x = sub.add_parser("add")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-n", "--name", required=True)
    x.add_argument("--connects", required=True,
                   help="comma-separated group names")
    x.add_argument("--ip-suffix", type=int, default=254)
    x.set_defaults(func=_cmd_router_add)
    x = sub.add_parser("remove")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-n", "--name", required=True)
    x.set_defaults(func=_cmd_router_remove)
    return p


def _run_router(argv):
    args = _build_router_parser().parse_args(argv)
    try:
        return args.func(args)
    except (NetLabError, ConfigurationError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1


def _cmd_service_list(args):
    topo = load_topology(args.file)
    if not topo.services:
        print("No services defined in this topology.")
        return 0
    print(f"Services in {args.file}:")
    for s in topo.services:
        print(f"  {s.type:<10} group={s.group} ip_suffix={s.ip_suffix} "
              f"upstream={s.upstream} dhcp_range={s.dhcp_range}")
    return 0


def _cmd_service_up(args):
    topo = load_topology(args.file)
    from .topology import ServiceSpec
    new = ServiceSpec(
        type=args.type, group=args.group, ip_suffix=args.ip_suffix,
        upstream=args.upstream,
        dhcp_range=tuple(args.dhcp_range),
    )
    new.validate()
    svc = Cluster(topo)._make_service(new)
    svc.deploy()
    print(f"Service {new.type} up on group {new.group}")
    return 0


def _cmd_service_down(args):
    topo = load_topology(args.file)
    from .services import DnsmasqService
    from .topology import ServiceSpec
    spec = ServiceSpec(type="dnsmasq", group=args.group)
    DnsmasqService(
        spec=spec, client=Cluster(topo)._client,
        topology=topo, cluster_name=topo.name,
    ).destroy()
    print(f"Service on group {args.group} stopped")
    return 0


def _cmd_service_test_dhcp(args):
    topo = load_topology(args.file)
    spec = topo.group(args.group)
    from ipaddress import IPv4Network
    net = IPv4Network(spec.subnet, strict=False)
    service_spec = next(
        (s for s in topo.services
         if s.group == args.group and s.type == "dnsmasq"),
        None,
    )
    if service_spec is None:
        print(f"Error: no dnsmasq service defined for group '{args.group}'",
              file=sys.stderr)
        return 1
    dnsmasq_ip = str(net.network_address + service_spec.ip_suffix)
    print(f"Testing DHCP on {args.group} via dnsmasq at {dnsmasq_ip}")
    print("(best-effort test; requires internet for apk add.)")

    import docker as _docker
    client = _docker.from_env()
    test_container_name = f"netlab-dhcp-test-{args.group}"
    try:
        c = client.containers.get(test_container_name)
        c.remove(force=True)
    except _docker.errors.NotFound:
        pass

    try:
        c = client.containers.run(
            image="alpine:3.19",
            command=["sh", "-c",
                     "apk add --no-cache dhclient iproute2 >/dev/null 2>&1 "
                     "&& tail -f /dev/null"],
            name=test_container_name,
            detach=True,
            network=f"netlab-{args.group}",
            cap_add=["NET_ADMIN", "NET_RAW"],
        )
    except Exception as exc:
        print(f"Error: could not start test container: {exc}",
              file=sys.stderr)
        return 1

    import time
    time.sleep(6)
    try:
        c.exec_run(["ip", "addr", "flush", "dev", "eth0"])
        result = c.exec_run(["dhclient", "eth0"])
        if result.exit_code != 0:
            print("dhclient failed:")
            print(result.output.decode(errors="ignore"))
        addr = c.exec_run(["ip", "-4", "addr", "show", "eth0"])
        print(addr.output.decode(errors="ignore"))
    finally:
        c.remove(force=True)
    return 0


def _build_service_parser():
    p = argparse.ArgumentParser(prog="netlab service")
    sub = p.add_subparsers(dest="service_command", required=True)
    x = sub.add_parser("list")
    x.add_argument("-f", "--file", required=True)
    x.set_defaults(func=_cmd_service_list)
    x = sub.add_parser("up")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.add_argument("--type", default="dnsmasq", choices=["dnsmasq"])
    x.add_argument("--ip-suffix", type=int, default=250)
    x.add_argument("--upstream", default="8.8.8.8")
    x.add_argument("--dhcp-range", type=int, nargs=2,
                   default=[100, 200], dest="dhcp_range")
    x.set_defaults(func=_cmd_service_up)
    x = sub.add_parser("down")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.set_defaults(func=_cmd_service_down)
    x = sub.add_parser("test-dhcp")
    x.add_argument("-f", "--file", required=True)
    x.add_argument("-g", "--group", required=True)
    x.set_defaults(func=_cmd_service_test_dhcp)
    return p


def _run_service(argv):
    args = _build_service_parser().parse_args(argv)
    try:
        return args.func(args)
    except (NetLabError, ConfigurationError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1

def _cmd_web(args):
    """Launch the web UI in a native window, or fall back to the browser."""
    import sys
    import threading
    import time
    import webbrowser

    webview = None
    try:
        import webview as _webview
        webview = _webview
    except ImportError:
        print(
            "Note: pywebview not installed. Falling back to browser mode.\n"
            "To use native window: pip install pywebview --no-deps",
            file=sys.stderr,
        )

    try:
        import uvicorn
        from .web.app import create_app
    except ImportError as exc:
        print(f"Missing dependency: {exc}", file=sys.stderr)
        return 1

    def run_server():
        app = create_app()
        uvicorn.run(app, host=args.host, port=args.port, log_level="error")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1.5)

    url = f"http://{args.host}:{args.port}"

    print("=" * 50)
    print("POWRED BY github.com/KHOSROW-II")
    print("(KOXXH STUDIO)")
    print("=" * 50)
    print()

    url = f"http://{args.host}:{args.port}"

    if webview is not None:
        try:
            webview.create_window(
                title="NetLab - Network Simulation",
                url=url,
                width=1400,
                height=900,
                background_color="#0d1117",
                text_select=True,
            )
            webview.start()
            return 0
        except Exception as exc:
            print(
                f"Native window failed: {exc}. Falling back to browser.",
                file=sys.stderr,
            )

    print(f"NetLab is opening in your default browser at {url}")
    print("POWRED BY github.com/KHOSROW-II")
    print("(KOXXH STUDIO)")
    webbrowser.open(url)
    print("Press Ctrl+C to stop the server.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nServer stopped.")
    return 0


def _build_web_parser():
    p = argparse.ArgumentParser(prog="netlab web")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=_cmd_web)
    return p

# --- dispatcher ---------------------------------------------------------------

def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "ipam":
        return _run_ipam(argv[1:])
    if argv and argv[0] == "cluster":
        return _run_cluster(argv[1:])
    if argv and argv[0] == "viz":
        return _run_viz(argv[1:])
    if argv and argv[0] == "example":
        return _run_example(argv[1:])
    if argv and argv[0] == "protocol":
        return _run_protocol(argv[1:])
    if argv and argv[0] == "router":
        return _run_router(argv[1:])
    if argv and argv[0] == "service":
        return _run_service(argv[1:])
    if argv and argv[0] == "doctor":
        args = _build_doctor_parser().parse_args(argv[1:])
        return args.func(args)
    if argv and argv[0] == "web":
        args = _build_web_parser().parse_args(argv[1:])
        return args.func(args)
    return _run_deploy(argv)


if __name__ == "__main__":
    sys.exit(main())