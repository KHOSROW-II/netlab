"""Sample topologies shipped with NetLab."""
from pathlib import Path

import yaml

from .topology import LabTopology

EXAMPLE_TOPOLOGY_YAML = """\
name: netlab-demo
image: nicolaka/netshoot:latest

groups:
  - name: grpA
    subnet: 10.10.0.0/24
    host_count: 3
    start_offset: 10
    gateway_offset: 1
    topology: bus

  - name: grpB
    subnet: 10.20.0.0/24
    host_count: 3
    topology: ring

  - name: grpC
    subnet: 10.30.0.0/24
    host_count: 2
    start_offset: 20
    topology: star

routers:
  - name: r1
    connects: [grpA, grpC]
    ip_suffix: 254

services:
  - type: dnsmasq
    group: grpA
    ip_suffix: 250
    upstream: 8.8.8.8
    dhcp_range: [100, 200]
"""


def write_example(path: str) -> None:
    """Write the sample topology YAML to `path` (creating parents)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(EXAMPLE_TOPOLOGY_YAML, encoding="utf-8")


def save_topology(topo: LabTopology, path: str) -> None:
    """Serialize a LabTopology back to YAML."""
    data = {
        "name": topo.name,
        "image": topo.image,
        "groups": [
            {
                "name": g.name, "subnet": g.subnet,
                "host_count": g.host_count,
                "start_offset": g.start_offset,
                "gateway_offset": g.gateway_offset,
                "dns_servers": list(g.dns_servers),
                "search_domains": list(g.search_domains),
                "topology": g.topology.value,
            }
            for g in topo.groups
        ],
        "routers": [
            {
                "name": r.name,
                "connects": list(r.connects),
                "ip_suffix": r.ip_suffix,
                "image": r.image,
            }
            for r in topo.routers
        ],
        "services": [
            {
                "type": s.type, "group": s.group,
                "ip_suffix": s.ip_suffix,
                "upstream": s.upstream,
                "dhcp_range": list(s.dhcp_range),
            }
            for s in topo.services
        ],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")