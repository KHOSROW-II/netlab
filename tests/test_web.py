"""Tests for the web UI backend."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from netlab.web.app import create_app


@pytest.fixture
def client():
    with patch("netlab.web.routes.docker.from_env"):
        yield TestClient(create_app())


# --- pages -----------------------------------------------------------------

class TestIndex:
    def test_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "NetLab" in r.text
        assert 'id="editor-svg"' in r.text
        assert 'data-view="editor"' in r.text

    def test_has_sidebar(self, client):
        r = client.get("/")
        assert 'class="sidebar"' in r.text
        assert 'data-view="monitor"' in r.text
        assert 'data-view="calculator"' in r.text

    def test_has_routing_banner(self, client):
        r = client.get("/")
        assert 'id="routing-banner"' in r.text

    def test_has_force_deploy_button(self, client):
        r = client.get("/")
        assert 'id="ed-force-deploy"' in r.text

    def test_has_validate_button(self, client):
        r = client.get("/")
        assert 'id="mon-validate"' in r.text


# --- regression: all core endpoints must be reachable --------------------

class TestCoreEndpoints:
    """Regression guard: any of these returning 404 means a route was lost."""

    def test_topologies_200(self, client):
        r = client.get("/api/topologies")
        assert r.status_code == 200
        assert "topologies" in r.json()

    def test_status_200(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200

    def test_routing_200(self, client):
        r = client.get("/api/routing")
        assert r.status_code == 200

    def test_graph_200(self, client):
        r = client.get("/api/graph")
        assert r.status_code == 200


# --- status ---------------------------------------------------------------

class TestStatus:
    def test_empty_cluster(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        d = r.json()
        assert d["cluster"] == "(none)"
        assert d["groups"] == []
        assert d["routers"] == []
        assert d["services"] == []
        assert d["placeholders"] == []


# --- routing --------------------------------------------------------------

class TestRouting:
    def test_status_no_topology(self, client):
        r = client.get("/api/routing")
        assert r.status_code == 200
        d = r.json()
        assert d["needed"] is False
        assert d["enabled"] is True
        assert "can_fix" in d
        assert "hint" in d

    def test_enable_no_topology(self, client):
        r = client.post("/api/routing/enable")
        assert r.status_code == 400


# --- graph ----------------------------------------------------------------

class TestGraph:
    def test_empty_graph(self, client):
        r = client.get("/api/graph")
        assert r.status_code == 200
        d = r.json()
        assert d["nodes"] == []
        assert d["edges"] == []
        assert d["networks"] == []
        assert d["groups"] == []

    def test_nodes_have_interfaces(self, client):
        r = client.get("/api/graph")
        d = r.json()
        for n in d["nodes"]:
            assert "interfaces" in n


# --- validate -------------------------------------------------------------

class TestValidate:
    def test_no_containers(self, client):
        r = client.post("/api/validate", json={})
        assert r.status_code == 200
        d = r.json()
        assert d["tests"] == []
        assert d["summary"]["total"] == 0

    def test_last_empty(self, client):
        r = client.get("/api/validate/last")
        assert r.status_code == 200
        assert r.json()["tests"] == []


# --- editor ---------------------------------------------------------------

class TestEditor:
    def test_deploy_invalid_topology(self, client):
        r = client.post("/api/editor/deploy", json={
            "name": "t", "groups": [], "routers": [], "services": [],
        })
        assert r.status_code in (400, 409)

    def test_deploy_invalid_subnet(self, client):
        r = client.post("/api/editor/deploy", json={
            "name": "t",
            "groups": [{"name": "g", "subnet": "bad", "host_count": 1}],
            "routers": [], "services": [],
        })
        assert r.status_code == 400

    def test_save_invalid_name(self, client):
        r = client.post("/api/editor/save", json={
            "name": "bad/name",
            "groups": [{"name": "g", "subnet": "10.0.0.0/24",
                        "host_count": 1}],
            "routers": [], "services": [],
        })
        assert r.status_code == 400

    def test_load_missing_path(self, client):
        r = client.post("/api/editor/load", json={})
        assert r.status_code == 400

    def test_load_nonexistent_file(self, client):
        r = client.post("/api/editor/load", json={"path": "/no/such.yaml"})
        assert r.status_code == 400


class TestEditorPreview:
    def test_preview_computes_ips(self, client):
        r = client.post("/api/editor/preview", json={
            "name": "t",
            "groups": [
                {"name": "g1", "subnet": "10.10.0.0/24", "host_count": 3},
            ],
            "routers": [], "services": [],
        })
        assert r.status_code == 200
        d = r.json()
        assert len(d["groups"]) == 1
        g = d["groups"][0]
        assert g["gateway"] == "10.10.0.1"
        assert g["hosts"][0]["ip"] == "10.10.0.10"
        assert g["hosts"][2]["ip"] == "10.10.0.12"

    def test_preview_router_ips(self, client):
        r = client.post("/api/editor/preview", json={
            "name": "t",
            "groups": [
                {"name": "g1", "subnet": "10.10.0.0/24", "host_count": 2},
                {"name": "g2", "subnet": "10.20.0.0/24", "host_count": 2},
            ],
            "routers": [
                {"name": "r1", "connects": ["g1", "g2"], "ip_suffix": 254},
            ],
            "services": [],
        })
        assert r.status_code == 200
        d = r.json()
        assert len(d["routers"]) == 1
        r1 = d["routers"][0]
        assert r1["interfaces"]["g1"] == "10.10.0.254"
        assert r1["interfaces"]["g2"] == "10.20.0.254"


# --- deploy actions -------------------------------------------------------

class TestDeploy:
    def test_missing_file(self, client):
        r = client.post("/api/deploy", json={})
        assert r.status_code == 400

    def test_nonexistent_file(self, client):
        r = client.post("/api/deploy", json={"file": "/no/such.yaml"})
        assert r.status_code == 400


class TestForceDeploy:
    def test_invalid_topology(self, client):
        r = client.post("/api/editor/force-deploy", json={
            "name": "t", "groups": [], "routers": [], "services": [],
        })
        assert r.status_code in (400, 409)


# --- exec / container actions --------------------------------------------

class TestExec:
    def test_invalid_host(self, client):
        r = client.post("/api/exec",
                        json={"host": "evil", "command": "id"})
        assert r.status_code == 400

    def test_missing_host(self, client):
        r = client.post("/api/exec", json={"command": "id"})
        assert r.status_code == 400

    def test_missing_command(self, client):
        r = client.post("/api/exec", json={"host": "netlab-x"})
        assert r.status_code == 400


class TestContainerActions:
    def test_stop_invalid_name(self, client):
        r = client.post("/api/container/evil/stop")
        assert r.status_code == 400

    def test_start_invalid_name(self, client):
        r = client.post("/api/container/evil/start")
        assert r.status_code == 400

    def test_logs_invalid_name(self, client):
        r = client.post("/api/container/evil/logs")
        assert r.status_code == 400


# --- calculator -----------------------------------------------------------

class TestSubnetAnalyze:
    def test_ipv4(self, client):
        r = client.post("/api/subnet/analyze",
                        json={"ip": "192.168.1.10", "subnet": "/24"})
        assert r.status_code == 200
        d = r.json()
        assert d["kind"] == "ipv4"
        f = d["fields"]
        # اصلاح کلیدها برای هماهنگی با خروجی API
        assert f["network"] == "192.168.1.0"
        assert f["broadcast"] == "192.168.1.255"
        assert f["hosts"] == 254

    def test_ipv4_netmask_input(self, client):
        r = client.post("/api/subnet/analyze",
                        json={"ip": "10.0.0.5",
                              "subnet": "255.255.255.0"})
        assert r.status_code == 200
        d = r.json()
        assert d["kind"] == "ipv4"
        assert d["fields"]["prefix_length"] == 24

    def test_missing_ip(self, client):
        r = client.post("/api/subnet/analyze", json={})
        assert r.status_code == 400

    def test_invalid_ip(self, client):
        r = client.post("/api/subnet/analyze",
                        json={"ip": "not-an-ip"})
        assert r.status_code == 400


class TestSubnetSplit:
    def test_split_by_count(self, client):
        r = client.post("/api/subnet/split",
                        json={"subnet": "10.0.0.0/16", "count": 4})
        assert r.status_code == 200
        d = r.json()
        assert len(d["subnets"]) == 4
        assert d["subnets"][0]["network"] == "10.0.0.0/18"
        assert d["subnets"][1]["network"] == "10.0.64.0/18"

    def test_split_by_prefix(self, client):
        r = client.post("/api/subnet/split",
                        json={"subnet": "192.168.1.0/24", "prefix": 26})
        assert r.status_code == 200
        d = r.json()
        assert len(d["subnets"]) == 4
        assert d["subnets"][0]["usable_hosts"] == 62

    def test_missing_subnet(self, client):
        r = client.post("/api/subnet/split", json={})
        assert r.status_code == 400

    def test_missing_params(self, client):
        r = client.post("/api/subnet/split",
                        json={"subnet": "10.0.0.0/16"})
        assert r.status_code == 400