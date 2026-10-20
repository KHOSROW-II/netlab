"""Environment and package integrity checks, plus auto-remediation."""
import shutil

import docker

from . import __version__
from . import animate as animate_module
from . import examples as examples_module
from . import protocols as protocols_module
from . import viz
from .cluster import Cluster
from .firewall import SYSCTL_KEY, FirewallManager
from .group import Group
from .host_manager import HostManager
from .ipam import HostIPPlanner
from .lab import Lab
from .network_manager import NetworkManager
from .platform import detect_platform
from .router import Router
from .services import DnsmasqService
from .topology import LabTopology

REQUIRED_LAB = ["deploy", "destroy", "run_connectivity_check", "print_summary"]
REQUIRED_NETWORK_MGR = ["create", "ensure_absent", "remove_all_for_cluster"]
REQUIRED_HOST_MGR = [
    "ensure_image", "create", "create_multi", "ping", "exec_cmd",
    "set_dns", "set_ip", "set_default_route", "enable_forwarding",
    "stop", "start", "container_status", "remove_all",
]
REQUIRED_PLANNER = ["plan", "gateway"]
REQUIRED_GROUP = ["deploy", "destroy", "exec", "set_dns", "set_ip"]
REQUIRED_CLUSTER = [
    "deploy", "destroy", "exec", "set_dns", "set_ip", "status",
    "firewall_install", "firewall_status", "firewall_revoke",
]
REQUIRED_TOPOLOGY = ["validate", "group"]
REQUIRED_VIZ = ["build_graph", "render_ascii", "to_dot"]
REQUIRED_EXAMPLES = ["write_example", "save_topology"]
REQUIRED_PROTOCOLS = [
    "ARPSimulator", "ARPLive", "ICMPSimulator", "ICMPLive",
    "DNSSimulator", "DNSLive", "DHCPSimulator",
    "render_timeline", "render_summary",
]
REQUIRED_ROUTER = ["deploy", "host_default_gateway"]
REQUIRED_SERVICE = ["deploy", "destroy"]
REQUIRED_ANIMATE = ["animate_events"]
REQUIRED_FIREWALL = [
    "has_routers", "state", "install", "uninstall", "persist_commands",
]


def _missing(obj, names):
    return [n for n in names if not hasattr(obj, n)]


def run_checks() -> int:
    print(f"NetLab {__version__} - environment check")
    print("-" * 55)
    ok = True

    checks = [
        (Lab, REQUIRED_LAB, "Lab"),
        (NetworkManager, REQUIRED_NETWORK_MGR, "NetworkManager"),
        (HostManager, REQUIRED_HOST_MGR, "HostManager"),
        (HostIPPlanner, REQUIRED_PLANNER, "HostIPPlanner"),
        (Group, REQUIRED_GROUP, "Group"),
        (Cluster, REQUIRED_CLUSTER, "Cluster"),
        (LabTopology, REQUIRED_TOPOLOGY, "LabTopology"),
        (viz, REQUIRED_VIZ, "viz"),
        (examples_module, REQUIRED_EXAMPLES, "examples"),
        (protocols_module, REQUIRED_PROTOCOLS, "protocols"),
        (Router, REQUIRED_ROUTER, "Router"),
        (DnsmasqService, REQUIRED_SERVICE, "DnsmasqService"),
        (animate_module, REQUIRED_ANIMATE, "animate"),
        (FirewallManager, REQUIRED_FIREWALL, "FirewallManager"),
    ]
    for obj, methods, label in checks:
        missing = _missing(obj, methods)
        if missing:
            print(f"[FAIL] {label} missing: {missing}")
            ok = False
        else:
            print(f"[ OK ] {label} interface complete")

    adapter = detect_platform()
    print(f"[ OK ] Platform adapter: {adapter.name}")
    print(f"[ OK ] Docker: {adapter.docker_hint()}")

    try:
        client = docker.from_env()
        client.ping()
        version = client.version().get("Version", "unknown")
        print(f"[ OK ] Docker daemon reachable (version {version})")
    except Exception as exc:
        print(f"[FAIL] Docker daemon: {exc}")
        ok = False

    try:
        import netgraph  # noqa: F401
        import matplotlib  # noqa: F401
        print("[ OK ] viz extras installed (netgraph + matplotlib)")
    except ImportError:
        print("[ -- ] viz extras not installed "
              "(install: pip install -e '.[viz]')")

    if shutil.which("iptables"):
        print("[ OK ] iptables present")
    else:
        print("[ -- ] iptables not found (cross-group routing may not work)")

    value = adapter.read_sysctl(SYSCTL_KEY)
    if value == "1":
        print("[ -- ] br_netfilter enabled: run "
              "`netlab doctor --fix`")
    elif value == "0":
        print("[ OK ] br_netfilter disabled (router forwarding will work)")
    else:
        print(f"[ -- ] br_netfilter status unknown ({value!r})")

    print("-" * 55)
    print("All checks passed." if ok else "Some checks failed.")
    return 0 if ok else 1


def run_fixes(topology: LabTopology | None = None) -> int:
    """Run checks, attempt fixes, then re-check. Returns final exit code."""
    from .fixer import Fixer

    run_checks()
    print()
    print("Fixes")
    print("-" * 55)
    report = Fixer(topology).run()
    report.print()
    print()
    print("Re-check after fixes")
    print("-" * 55)
    return run_checks()