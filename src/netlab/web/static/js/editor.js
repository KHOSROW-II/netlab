"use strict";

(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const NODE_W_GROUP = 200;
  const GROUP_HEADER = 56;
  const GROUP_ROW = 16;
  const ROUTER_R = 30;
  const SERVICE_W = 160;
  const SERVICE_H = 40;
  const ZOOM_MIN = 0.3;
  const ZOOM_MAX = 3;

  const state = {
    name: "netlab-editor",
    image: "nicolaka/netshoot:latest",
    nodes: [],
    edges: [],
    selected: null,
    counters: {group: 0, router: 0, service: 0},
    drag: null,
    view: {x: 0, y: 0, s: 1},
    panning: null,
    connectMode: false,
    connectSource: null,
  };

  let svg, props, status, viewport;

  function el(tag, attrs = {}) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  }

  function svgPoint(evt) {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return {x: (p.x - state.view.x) / state.view.s,
            y: (p.y - state.view.y) / state.view.s};
  }

  function applyView() {
    if (viewport) {
      viewport.setAttribute(
        "transform",
        `translate(${state.view.x}, ${state.view.y}) scale(${state.view.s})`,
      );
    }
  }

  function setStatus(text, kind) {
    status.textContent = text;
    status.className = "statusbar" + (kind ? " " + kind : "");
  }

  function ipFromCidr(cidr, offset) {
    try {
      const [ip, prefix] = cidr.split("/");
      const parts = ip.split(".").map(Number);
      const base = (parts[0] << 24) | (parts[1] << 16) |
                   (parts[2] << 8) | parts[3];
      const block = 2 ** (32 - parseInt(prefix));
      const netAddr = (base >>> 0) - ((base >>> 0) % block);
      const ipInt = netAddr + offset;
      return [
        (ipInt >>> 24) & 255, (ipInt >>> 16) & 255,
        (ipInt >>> 8) & 255, ipInt & 255,
      ].join(".");
    } catch (_) { return "?"; }
  }

  function autoGroupName() {
    state.counters.group += 1;
    return "grp" + String.fromCharCode(64 + state.counters.group);
  }

  function autoSubnet(n) { return `10.${n * 10}.0.0/24`; }

  function findNode(id) { return state.nodes.find(n => n.id === id); }

  // ---------- factories ----------

  function addGroup(topology) {
    const n = state.counters.group + 1;
    const id = `group-${n}`;
    state.counters.group = n;
    const node = {
      id, kind: "group",
      x: 80 + (state.nodes.length % 3) * 60,
      y: 80 + (state.nodes.length % 5) * 60,
      name: autoGroupName(),
      subnet: autoSubnet(n),
      host_count: 3,
      start_offset: 10,
      gateway_offset: 1,
      topology: topology || "bus",
      dns_servers: [],
      search_domains: [],
    };
    state.nodes.push(node);
    state.selected = id;
    render(); renderProps();
    setStatus(`Added group ${node.name} (${node.topology})`, "ok");
  }

  function addRouter() {
    const n = state.counters.router + 1;
    const id = `router-${n}`;
    state.counters.router = n;
    const node = {
      id, kind: "router",
      x: 420 + (state.nodes.length % 3) * 40,
      y: 160 + (state.nodes.length % 4) * 80,
      name: `r${n}`, ip_suffix: 254,
      image: "nicolaka/netshoot:latest",
    };
    state.nodes.push(node);
    state.selected = id;
    render(); renderProps();
    setStatus(`Added router ${node.name}`, "ok");
  }

  function addService() {
    if (!state.nodes.some(n => n.kind === "group")) {
      setStatus("Add a group first.", "error");
      return;
    }
    const n = state.counters.service + 1;
    const id = `service-${n}`;
    state.counters.service = n;
    const firstGroup = state.nodes.find(n => n.kind === "group");
    const node = {
      id, kind: "service",
      x: 720, y: 160 + (state.nodes.length % 4) * 80,
      type: "dnsmasq",
      group: firstGroup.name,
      ip_suffix: 250, upstream: "8.8.8.8",
      dhcp_range: [100, 200],
    };
    state.nodes.push(node);
    state.selected = id;
    render(); renderProps();
    setStatus(`Added ${node.type} on ${node.group}`, "ok");
  }

  function deleteSelected() {
    if (!state.selected) return;
    const id = state.selected;
    state.nodes = state.nodes.filter(n => n.id !== id);
    state.edges = state.edges.filter(e => e.from !== id && e.to !== id);
    state.selected = null;
    render(); renderProps();
    setStatus("Deleted", "ok");
  }

  // ---------- manual connection ----------

  function toggleConnectMode() {
    state.connectMode = !state.connectMode;
    state.connectSource = null;
    const btn = $("ed-connect");
    btn.classList.toggle("btn-primary", state.connectMode);
    if (state.connectMode) {
      setStatus("Connect mode: click source node, then target node", "ok");
    } else {
      setStatus("Connect mode off", "ok");
    }
    render();
  }

  function tryConnect(aId, bId) {
    const a = findNode(aId);
    const b = findNode(bId);
    if (!a || !b || a === b) return;
    const kinds = [a.kind, b.kind].sort().join("|");
    if (kinds === "group|router") {
      const router = a.kind === "router" ? a : b;
      const group = a.kind === "group" ? a : b;
      const exists = state.edges.some(
        e => e.kind === "route" &&
             ((e.from === router.id && e.to === group.id) ||
              (e.from === group.id && e.to === router.id))
      );
      if (exists) {
        setStatus("Already connected", "error");
        return;
      }
      state.edges.push({from: router.id, to: group.id, kind: "route"});
      setStatus(`Connected ${router.name} ↔ ${group.name}`, "ok");
    } else if (kinds === "group|service") {
      // Service is bound to a group already via spec — no edge needed
      setStatus("Services attach to their group automatically", "error");
    } else if (kinds === "router|router") {
      setStatus("Router↔router connections are not supported yet", "error");
    } else {
      setStatus(`Cannot connect ${a.kind} ↔ ${b.kind}`, "error");
    }
  }

  // ---------- rendering ----------

  function nodeBounds(node) {
    if (node.kind === "group") {
      const h = GROUP_HEADER + node.host_count * GROUP_ROW + 8;
      return {x: node.x, y: node.y, w: NODE_W_GROUP, h};
    }
    if (node.kind === "router") {
      return {x: node.x - ROUTER_R, y: node.y - ROUTER_R,
              w: ROUTER_R * 2, h: ROUTER_R * 2};
    }
    return {x: node.x, y: node.y, w: SERVICE_W, h: SERVICE_H};
  }

  function render() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const defs = el("defs");
    const pat = el("pattern", {
      id: "grid-pat", width: 24, height: 24, patternUnits: "userSpaceOnUse",
    });
    pat.appendChild(el("path", {
      d: "M 24 0 L 0 0 0 24", fill: "none", stroke: "#1c2128", "stroke-width": "1",
    }));
    defs.appendChild(pat);
    svg.appendChild(defs);
    svg.appendChild(el("rect", {
      x: 0, y: 0, width: "100%", height: "100%", fill: "url(#grid-pat)",
    }));

    viewport = el("g", {id: "editor-viewport"});
    svg.appendChild(viewport);

    for (const e of state.edges) {
      const a = findNode(e.from), b = findNode(e.to);
      if (!a || !b) continue;
      const ab = nodeBounds(a), bb = nodeBounds(b);
      const ax = ab.x + ab.w / 2, ay = ab.y + ab.h / 2;
      const bx = bb.x + bb.w / 2, by = bb.y + bb.h / 2;
      viewport.appendChild(el("line", {
        x1: ax, y1: ay, x2: bx, y2: by, class: "edge edge-" + e.kind,
      }));
    }

    for (const n of state.nodes) {
      const g = el("g", {class: "node-group", "data-id": n.id});
      if (n.kind === "group") drawGroup(g, n);
      else if (n.kind === "router") drawRouter(g, n);
      else drawService(g, n);
      if (state.selected === n.id) g.classList.add("node-selected");
      if (state.connectSource === n.id) g.classList.add("node-connect-source");
      g.addEventListener("mousedown", onNodeMouseDown);
      g.addEventListener("click", onNodeClick);
      viewport.appendChild(g);
    }

    applyView();
  }

  function drawGroup(g, n) {
    const b = nodeBounds(n);
    g.appendChild(el("rect", {
      x: b.x, y: b.y, width: b.w, height: b.h, rx: 6, ry: 6,
      class: "group-body",
    }));
    const title = el("text", {
      x: b.x + 10, y: b.y + 18, class: "group-title",
    });
    title.textContent = n.name;
    g.appendChild(title);
    const meta = el("text", {
      x: b.x + 10, y: b.y + 34, class: "group-meta",
    });
    meta.textContent = `${n.subnet} · ${n.topology} · ${n.host_count}h`;
    g.appendChild(meta);
    const gwIp = ipFromCidr(n.subnet, n.gateway_offset || 1);
    const gwLabel = el("text", {
      x: b.x + 14, y: b.y + 50, class: "editor-gw",
    });
    gwLabel.textContent = `gateway ${gwIp}`;
    g.appendChild(gwLabel);
    for (let i = 0; i < n.host_count; i++) {
      const hostIp = ipFromCidr(n.subnet, (n.start_offset || 10) + i);
      const row = el("text", {
        x: b.x + 14, y: b.y + GROUP_HEADER + 18 + i * GROUP_ROW,
        class: "editor-ip",
      });
      row.textContent = `host${i + 1}  ${hostIp}`;
      g.appendChild(row);
    }
  }

  function drawRouter(g, n) {
    g.appendChild(el("circle", {
      cx: n.x, cy: n.y, r: ROUTER_R,
      fill: "#5c3d7a", stroke: "#a371f7", "stroke-width": 1.5,
    }));
    const label = el("text", {
      x: n.x, y: n.y + 4, class: "node-label",
      "text-anchor": "middle", "font-size": "11",
    });
    label.textContent = n.name;
    g.appendChild(label);
  }

  function drawService(g, n) {
    const b = nodeBounds(n);
    g.appendChild(el("rect", {
      x: b.x, y: b.y, width: b.w, height: b.h, rx: 4, ry: 4,
      class: "node-service",
    }));
    const group = state.nodes.find(x => x.kind === "group" && x.name === n.group);
    const svcIp = group ? ipFromCidr(group.subnet, n.ip_suffix || 250) : "?";
    const label = el("text", {
      x: b.x + 10, y: b.y + 16, class: "service-label",
    });
    label.textContent = `${n.type} ${svcIp}`;
    g.appendChild(label);
    const sub = el("text", {
      x: b.x + 10, y: b.y + 30, class: "group-meta",
    });
    sub.textContent = `on ${n.group}`;
    g.appendChild(sub);
  }

  // ---------- node click / drag ----------

  function onNodeClick(evt) {
    evt.stopPropagation();
    const id = evt.currentTarget.getAttribute("data-id");
    if (state.connectMode) {
      if (!state.connectSource) {
        state.connectSource = id;
        setStatus("Source selected. Click target node.", "ok");
        render();
      } else {
        const src = state.connectSource;
        state.connectSource = null;
        state.connectMode = false;
        $("ed-connect").classList.remove("btn-primary");
        tryConnect(src, id);
        render(); renderProps();
      }
    } else {
      state.selected = id;
      render(); renderProps();
    }
  }

  function onNodeMouseDown(evt) {
    if (state.connectMode) return;  // no dragging in connect mode
    const g = evt.currentTarget;
    const id = g.getAttribute("data-id");
    const node = findNode(id);
    if (!node) return;
    evt.stopPropagation();
    const p = svgPoint(evt);
    state.drag = {id, dx: p.x - node.x, dy: p.y - node.y};
    document.addEventListener("mousemove", onNodeMouseMove);
    document.addEventListener("mouseup", onNodeMouseUp);
    evt.preventDefault();
  }

  function onNodeMouseMove(evt) {
    if (!state.drag) return;
    const node = findNode(state.drag.id);
    if (!node) return;
    const p = svgPoint(evt);
    node.x = Math.max(20, Math.min(1160, p.x - state.drag.dx));
    node.y = Math.max(20, Math.min(660, p.y - state.drag.dy));
    render();
  }

  function onNodeMouseUp() {
    state.drag = null;
    document.removeEventListener("mousemove", onNodeMouseMove);
    document.removeEventListener("mouseup", onNodeMouseUp);
  }

  // ---------- pan / zoom ----------

  function onWheel(evt) {
    evt.preventDefault();
    const factor = Math.exp(-evt.deltaY * 0.0015);
    const newS = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, state.view.s * factor));
    const rect = svg.getBoundingClientRect();
    const mx = evt.clientX - rect.left;
    const my = evt.clientY - rect.top;
    state.view.x = mx - (mx - state.view.x) * (newS / state.view.s);
    state.view.y = my - (my - state.view.y) * (newS / state.view.s);
    state.view.s = newS;
    applyView();
  }

  function onPanStart(evt) {
    if (state.connectMode) return;
    if (evt.target !== svg && evt.target.parentNode !== svg) return;
    const rect = svg.getBoundingClientRect();
    state.panning = {
      startX: evt.clientX - rect.left,
      startY: evt.clientY - rect.top,
      viewX: state.view.x, viewY: state.view.y,
    };
    document.addEventListener("mousemove", onPanMove);
    document.addEventListener("mouseup", onPanEnd);
  }

  function onPanMove(evt) {
    if (!state.panning) return;
    const rect = svg.getBoundingClientRect();
    const dx = (evt.clientX - rect.left) - state.panning.startX;
    const dy = (evt.clientY - rect.top) - state.panning.startY;
    state.view.x = state.panning.viewX + dx;
    state.view.y = state.panning.viewY + dy;
    applyView();
  }

  function onPanEnd() {
    state.panning = null;
    document.removeEventListener("mousemove", onPanMove);
    document.removeEventListener("mouseup", onPanEnd);
  }

  function resetZoom() { state.view = {x: 0, y: 0, s: 1}; applyView(); }
  function zoomBy(f) {
    state.view.s = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, state.view.s * f));
    applyView();
  }

  // ---------- properties panel ----------

  function renderProps() {
    props.innerHTML = "";
    if (!state.selected) {
      props.innerHTML = '<p class="muted">Select a node or add a new one.</p>';
      return;
    }
    const node = findNode(state.selected);
    if (!node) return;
    const title = document.createElement("h3");
    title.textContent = node.name || "(unnamed)";
    props.appendChild(title);
    const kind = document.createElement("div");
    kind.className = "kind";
    kind.textContent = node.kind;
    props.appendChild(kind);

    if (node.kind === "group") renderGroupProps(node);
    else if (node.kind === "router") renderRouterProps(node);
    else renderServiceProps(node);

    const actions = document.createElement("div");
    actions.className = "field-actions";
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-sm btn-danger";
    delBtn.textContent = "Delete node";
    delBtn.onclick = deleteSelected;
    actions.appendChild(delBtn);
    props.appendChild(actions);
  }

  function field(container, label, input) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const lbl = document.createElement("label");
    lbl.textContent = label;
    wrap.appendChild(lbl); wrap.appendChild(input);
    container.appendChild(wrap);
  }

  function renderGroupProps(node) {
    const nameIn = document.createElement("input");
    nameIn.value = node.name;
    nameIn.oninput = () => { node.name = nameIn.value; render(); };
    field(props, "Name", nameIn);

    const subnetIn = document.createElement("input");
    subnetIn.value = node.subnet;
    subnetIn.oninput = () => { node.subnet = subnetIn.value; render(); };
    field(props, "Subnet", subnetIn);

    const hostIn = document.createElement("input");
    hostIn.type = "number"; hostIn.min = "1"; hostIn.max = "30";
    hostIn.value = node.host_count;
    hostIn.oninput = () => {
      node.host_count = Math.max(1, Math.min(30, parseInt(hostIn.value) || 1));
      render();
    };
    field(props, "Host count", hostIn);

    const topoSel = document.createElement("select");
    ["bus", "star", "ring", "switch", "hub", "access_point"].forEach(t => {
      const opt = document.createElement("option");
      opt.value = t; opt.textContent = t;
      if (t === node.topology) opt.selected = true;
      topoSel.appendChild(opt);
    });
    topoSel.onchange = () => { node.topology = topoSel.value; render(); };
    field(props, "Topology", topoSel);

    const dnsIn = document.createElement("input");
    dnsIn.value = (node.dns_servers || []).join(", ");
    dnsIn.placeholder = "8.8.8.8, 1.1.1.1";
    dnsIn.oninput = () => {
      node.dns_servers = dnsIn.value.split(",").map(s => s.trim()).filter(Boolean);
    };
    field(props, "DNS servers", dnsIn);
  }

  function renderRouterProps(node) {
    const nameIn = document.createElement("input");
    nameIn.value = node.name;
    nameIn.oninput = () => { node.name = nameIn.value; render(); };
    field(props, "Name", nameIn);

    const ipIn = document.createElement("input");
    ipIn.type = "number"; ipIn.min = "2"; ipIn.max = "254";
    ipIn.value = node.ip_suffix;
    ipIn.oninput = () => {
      node.ip_suffix = Math.max(2, Math.min(254, parseInt(ipIn.value) || 254));
    };
    field(props, "IP suffix", ipIn);

    const groups = state.nodes.filter(n => n.kind === "group");
    const connected = new Set(
      state.edges.filter(e => e.from === node.id).map(e => e.to)
    );
    const wrap = document.createElement("div");
    wrap.className = "field";
    const lbl = document.createElement("label");
    lbl.textContent = "Connected groups";
    wrap.appendChild(lbl);
    const list = document.createElement("div");
    list.className = "checklist";
    if (!groups.length) {
      const p = document.createElement("p");
      p.className = "muted"; p.textContent = "(no groups)";
      p.style.fontSize = "11px";
      list.appendChild(p);
    }
    for (const g of groups) {
      const row = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = connected.has(g.id);
      cb.onchange = () => {
        if (cb.checked) {
          state.edges.push({from: node.id, to: g.id, kind: "route"});
        } else {
          state.edges = state.edges.filter(
            e => !(e.from === node.id && e.to === g.id)
          );
        }
        render();
      };
      row.appendChild(cb);
      row.appendChild(document.createTextNode(g.name || g.id));
      list.appendChild(row);
    }
    wrap.appendChild(list);
    props.appendChild(wrap);
  }

  function renderServiceProps(node) {
    const groupSel = document.createElement("select");
    state.nodes.filter(n => n.kind === "group").forEach(g => {
      const opt = document.createElement("option");
      opt.value = g.name; opt.textContent = g.name;
      if (g.name === node.group) opt.selected = true;
      groupSel.appendChild(opt);
    });
    groupSel.onchange = () => { node.group = groupSel.value; render(); };
    field(props, "Group", groupSel);

    const upstreamIn = document.createElement("input");
    upstreamIn.value = node.upstream;
    upstreamIn.oninput = () => { node.upstream = upstreamIn.value; };
    field(props, "Upstream DNS", upstreamIn);
  }

  // ---------- topology conversion ----------

  function toTopology() {
    const groups = state.nodes.filter(n => n.kind === "group").map(n => ({
      name: n.name, subnet: n.subnet, host_count: n.host_count,
      start_offset: n.start_offset || 10,
      gateway_offset: n.gateway_offset || 1,
      topology: n.topology || "bus",
      dns_servers: n.dns_servers || [],
      search_domains: n.search_domains || [],
    }));
    const routers = state.nodes.filter(n => n.kind === "router").map(n => ({
      name: n.name, ip_suffix: n.ip_suffix || 254,
      image: n.image || "nicolaka/netshoot:latest",
      connects: state.edges
        .filter(e => e.from === n.id)
        .map(e => findNode(e.to)).filter(Boolean).map(g => g.name),
    }));
    const services = state.nodes.filter(n => n.kind === "service").map(n => ({
      type: n.type, group: n.group,
      ip_suffix: n.ip_suffix || 250,
      upstream: n.upstream || "8.8.8.8",
      dhcp_range: n.dhcp_range || [100, 200],
    }));
    return {name: state.name, image: state.image, groups, routers, services};
  }

  // ---------- actions ----------

  async function save() {
    try {
      state.name = ($("ed-name").value || "netlab-editor").trim();
      const r = await postJSON("/api/editor/save", toTopology());
      setStatus(`Saved to ${r.path}`, "ok");
      const tt = await api("/api/topologies");
      const sel = $("ed-load");
      const cur = sel.value;
      sel.innerHTML = '<option value="">Load…</option>' +
        tt.topologies.map(t =>
          `<option value="${t.path}">${t.name}</option>`).join("");
      if (cur) sel.value = cur;
    } catch (e) {
      setStatus("Save failed: " + e.message, "error");
    }
  }

  async function deploy() {
    if (state.nodes.length === 0) {
      setStatus("Nothing to deploy — add groups first.", "error");
      return;
    }
    try {
      state.name = ($("ed-name").value || "netlab-editor").trim();
      setStatus("Deploying… (10–30s)", "ok");
      const r = await postJSON("/api/editor/deploy", toTopology());
      setStatus(`Deployed cluster ${r.cluster}`, "ok");
      await refreshStatus();
      await refreshRouting();
    } catch (e) {
      setStatus("Deploy failed: " + e.message, "error");
    }
  }

  async function forceDeploy() {
    if (state.nodes.length === 0) {
      setStatus("Nothing to deploy — add groups first.", "error");
      return;
    }
    const ok = confirm(
      "Force deploy will:\n" +
      "  1. Remove ALL netlab-* containers and networks (any cluster)\n" +
      "  2. Deploy this topology\n\n" +
      "Continue?"
    );
    if (!ok) return;
    try {
      state.name = ($("ed-name").value || "netlab-editor").trim();
      setStatus("Cleaning up and deploying… (10–30s)", "ok");
      const r = await postJSON("/api/editor/force-deploy", toTopology());
      setStatus(
        `Cleanup: ${r.cleanup.containers} containers, ` +
        `${r.cleanup.networks} networks. ` +
        `Deployed: ${r.cluster}`, "ok",
      );
      await refreshStatus();
      await refreshRouting();
    } catch (e) {
      setStatus("Force deploy failed: " + e.message, "error");
    }
  }

  async function loadFromPath(path) {
    if (!path) return;
    try {
      const data = await postJSON("/api/editor/load", {path});
      state.name = data.name;
      state.image = data.image || "nicolaka/netshoot:latest";
      state.nodes = data.nodes;
      state.edges = data.edges;
      state.selected = null;
      state.counters = {
        group: state.nodes.filter(n => n.kind === "group").length,
        router: state.nodes.filter(n => n.kind === "router").length,
        service: state.nodes.filter(n => n.kind === "service").length,
      };
      $("ed-name").value = state.name;
      resetZoom();
      render(); renderProps();
      setStatus(`Loaded ${data.name}`, "ok");
    } catch (e) {
      setStatus("Load failed: " + e.message, "error");
    }
  }

  // ---------- init ----------

  function init() {
    svg = $("editor-svg");
    props = $("editor-props");
    status = $("editor-status");
    $("ed-add-group").onclick = () => addGroup("bus");
    $("ed-add-router").onclick = addRouter;
    $("ed-add-service").onclick = addService;
    $("ed-connect").onclick = toggleConnectMode;
    $("ed-delete").onclick = deleteSelected;
    $("ed-save").onclick = save;
    $("ed-deploy").onclick = deploy;
    $("ed-force-deploy").onclick = forceDeploy;
    $("ed-load").onchange = (e) => loadFromPath(e.target.value);
    $("ed-name").oninput = () => { state.name = $("ed-name").value; };

    svg.addEventListener("wheel", onWheel, {passive: false});
    svg.addEventListener("mousedown", onPanStart);
    const zoomIn = $("ed-zoom-in");
    const zoomOut = $("ed-zoom-out");
    const zoomReset = $("ed-zoom-reset");
    if (zoomIn) zoomIn.onclick = () => zoomBy(1.25);
    if (zoomOut) zoomOut.onclick = () => zoomBy(0.8);
    if (zoomReset) zoomReset.onclick = resetZoom;

    document.addEventListener("keydown", (e) => {
      if (!$("view-editor").classList.contains("active")) return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea") return;
      if (e.key === "Delete" || e.key === "Backspace") {
        if (state.selected) { e.preventDefault(); deleteSelected(); }
      }
      if (e.key === "g") addGroup("bus");
      if (e.key === "r") addRouter();
      if (e.key === "c") toggleConnectMode();
    });

    // Empty editor by default
    render(); renderProps();
    setStatus("Empty editor. Add a group, load a topology, or press Deploy.", "ok");
  }

  window.NetLabEditor = {init, save, deploy, forceDeploy, loadFromPath};
})();