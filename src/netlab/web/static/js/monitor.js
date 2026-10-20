"use strict";

(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const R = 14;
  const ZOOM_MIN = 0.3, ZOOM_MAX = 3;

  const positions = {};
  let lastCluster = null;
  let lastData = null;
  let lastValidation = null;

  let svgEl = null, propsEl = null, netlistEl = null;
  let drag = null, panning = null;
  const view = {x: 0, y: 0, s: 1};
  let selectedEdgeId = null;

  function el(tag, attrs = {}) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  }

  function svgPoint(evt) {
    const pt = svgEl.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const p = pt.matrixTransform(svgEl.getScreenCTM().inverse());
    return {x: (p.x - view.x) / view.s, y: (p.y - view.y) / view.s};
  }

  function applyView() {
    const vp = svgEl.querySelector("#monitor-viewport");
    if (vp) vp.setAttribute("transform",
      `translate(${view.x}, ${view.y}) scale(${view.s})`);
  }

  function ipOf(node) {
    if (!node.interfaces || !node.interfaces.length) return "";
    return node.interfaces[0].ip;
  }

  function ipsOf(node) {
    return (node.interfaces || []).map(i => i.ip);
  }

  function findNode(name) {
    return (lastData?.nodes || []).find(n => n.name === name);
  }

  // ---------- layout ----------

  function layoutAll(data) {
    const groups = data.groups || [];
    const routers = data.nodes.filter(n => n.role === "router");
    const boxes = [];
    const gw = 340, gh = 440, gap = 24, rowMax = 3;
    let x = 24, y = 24, col = 0;

    for (const g of groups) {
      if (col >= rowMax) { col = 0; x = 24; y += gh + gap; }
      boxes.push({x, y, w: gw, h: gh, name: g.name,
                  subnet: g.subnet, type: g.type, host_count: g.host_count});

      const hosts = data.nodes
        .filter(n => n.role === "host" && n.group === g.name)
        .sort((a, b) => a.name.localeCompare(b.name));
      const devices = data.nodes
        .filter(n => ["switch","hub","ap"].includes(n.role) && n.group === g.name);
      const svcs = data.nodes
        .filter(n => n.role === "service" && n.group === g.name);

      // central device(s) at top-center
      devices.forEach((dev, i) => {
        if (!positions[dev.name]) {
          positions[dev.name] = {x: x + gw / 2, y: y + 82};
        }
      });
      // if no real device, create virtual central at top-center for bus/star
      const needCentral = ["bus", "star"].includes(g.type) && devices.length === 0;
      const centralKey = needCentral ? `__central__${g.name}` : null;
      if (centralKey && !positions[centralKey]) {
        positions[centralKey] = {
          x: x + gw / 2, y: y + 82, virtual: true,
          kind: g.type, group: g.name,
        };
      }

      // hosts grid (2 columns)
      hosts.forEach((h, i) => {
        if (!positions[h.name]) {
          positions[h.name] = {
            x: x + 90 + (i % 2) * 155,
            y: y + 175 + Math.floor(i / 2) * 52,
          };
        }
      });

      // services at bottom
      svcs.forEach((s, i) => {
        if (!positions[s.name]) {
          positions[s.name] = {
            x: x + gw / 2,
            y: y + gh - 60 + i * 36,
          };
        }
      });

      x += gw + gap;
      col++;
    }

    // routers on right
    let rx = Math.max(x + 40, 1100);
    let ry = 100;
    routers.forEach(r => {
      if (!positions[r.name]) positions[r.name] = {x: rx, y: ry};
      ry += 110;
    });
  }

  function resetPositions() {
    Object.keys(positions).forEach(k => delete positions[k]);
  }

  // ---------- rendering ----------

  function drawBackground() {
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
    const defs = el("defs");
    const pat = el("pattern", {
      id: "m-grid", width: 24, height: 24, patternUnits: "userSpaceOnUse",
    });
    pat.appendChild(el("path", {
      d: "M 24 0 L 0 0 0 24", fill: "none", stroke: "#1c2128",
    }));
    defs.appendChild(pat);
    svgEl.appendChild(defs);
    svgEl.appendChild(el("rect", {
      x: 0, y: 0, width: "100%", height: "100%",
      fill: "url(#m-grid)",
    }));
    svgEl.appendChild(el("g", {id: "monitor-viewport"}));
  }

  function drawBoxes(boxes) {
    const vp = svgEl.querySelector("#monitor-viewport");
    for (const b of boxes) {
      vp.appendChild(el("rect", {
        x: b.x, y: b.y, width: b.w, height: b.h, rx: 8, ry: 8,
        fill: "rgba(22,27,34,0.5)", stroke: "#30363d",
        "stroke-width": 1, "stroke-dasharray": "4 4",
      }));
      const title = el("text", {
        x: b.x + 12, y: b.y + 22,
        "font-family": "ui-monospace, monospace",
        "font-size": "12", fill: "#c9d1d9", "font-weight": "600",
      });
      title.textContent = b.name;
      vp.appendChild(title);
      const meta = el("text", {
        x: b.x + 12, y: b.y + 38,
        "font-family": "ui-monospace, monospace",
        "font-size": "10", fill: "#8b949e",
      });
      meta.textContent = `${b.subnet} · ${b.type} · ${b.host_count}h`;
      vp.appendChild(meta);
    }
  }

  function drawEdges(edges) {
    const vp = svgEl.querySelector("#monitor-viewport");
    const netGroups = {};
    for (const e of edges) {
      const a = positions[e.source], b = positions[e.target];
      if (!a || !b) continue;
      const line = el("line", {
        x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        class: "edge edge-" + e.kind +
               (selectedEdgeId === e.id ? " edge-selected" : ""),
        "data-edge-id": e.id,
      });
      line.style.cursor = "pointer";
      line.addEventListener("click", (evt) => {
        evt.stopPropagation();
        selectedEdgeId = e.id;
        showEdgeInfo(e);
        drawEdges(edges);
      });
      vp.appendChild(line);

      // label at midpoint
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      const netLabel = (e.network || "").replace("netlab-", "");
      const subnet = e.subnet || "";
      const label = el("text", {
        x: mx, y: my - 4,
        "text-anchor": "middle",
        "font-family": "ui-monospace, monospace",
        "font-size": "9", fill: "#58a6ff",
        "pointer-events": "none",
      });
      label.textContent = netLabel;
      vp.appendChild(label);
      const label2 = el("text", {
        x: mx, y: my + 8,
        "text-anchor": "middle",
        "font-family": "ui-monospace, monospace",
        "font-size": "8", fill: "#8b949e",
        "pointer-events": "none",
      });
      label2.textContent = subnet;
      vp.appendChild(label2);
    }
  }

  function drawNode(node, isVirtual) {
    const p = positions[node.name];
    if (!p) return;
    const vp = svgEl.querySelector("#monitor-viewport");
    const role = isVirtual ? "central" : node.role;
    const g = el("g", {
      class: "node-group node-" + role +
             (node.status ? " node-status-" + node.status : ""),
      "data-id": node.name,
      transform: `translate(${p.x}, ${p.y})`,
    });
    const r = role === "router" ? R + 4
      : role === "service" ? R - 4
      : role === "central" ? 18 : R;

    if (role === "central" || ["switch","hub","ap"].includes(role)) {
      g.appendChild(el("rect", {
        x: -22, y: -10, width: 44, height: 20, rx: 4, ry: 4,
        fill: "#2c5282", stroke: "#63b3ed", "stroke-width": 1.5,
      }));
    } else {
      g.appendChild(el("circle", {cx: 0, cy: 0, r}));
    }

    // label with name
    const nameLabel = el("text", {
      x: 0, y: r + 13, "text-anchor": "middle",
      "font-family": "ui-monospace, monospace",
      "font-size": "9", fill: "#c9d1d9",
    });
    nameLabel.textContent = isVirtual
      ? (p.kind || "central")
      : node.label;
    g.appendChild(nameLabel);

    // IP(s)
    const ips = isVirtual ? [] : ipsOf(node);
    if (ips.length) {
      const ipLabel = el("text", {
        x: 0, y: r + 25, "text-anchor": "middle",
        "font-family": "ui-monospace, monospace",
        "font-size": "8", fill: "#7ee787",
      });
      ipLabel.textContent = ips[0];
      g.appendChild(ipLabel);
      if (ips.length > 1) {
        const ipLabel2 = el("text", {
          x: 0, y: r + 35, "text-anchor": "middle",
          "font-family": "ui-monospace, monospace",
          "font-size": "8", fill: "#8b949e",
        });
        ipLabel2.textContent = ips.slice(1).join(", ");
        g.appendChild(ipLabel2);
      }
    }

    if (!isVirtual) {
      g.addEventListener("click", (evt) => {
        evt.stopPropagation();
        showNodeInfo(node);
      });
      g.addEventListener("mousedown", makeDragHandler(node.name));
    }
    vp.appendChild(g);
  }

  const handlers = {
    stop: async (host) => {
      try { await postJSON(`/api/container/${host}/stop`, {}); }
      catch (e) { alert(e.message); }
      refresh();
    },
    start: async (host) => {
      try { await postJSON(`/api/container/${host}/start`, {}); }
      catch (e) { alert(e.message); }
      refresh();
    },
    logs: async (host) => {
      try {
        const r = await postJSON(`/api/container/${host}/logs`, {});
        const pre = document.getElementById("mon-log");
        if (pre) { pre.style.display = "block";
                    pre.textContent = r.output || "(no logs)"; }
      } catch (e) { alert(e.message); }
    },
    terminal: (host) => {
      const sel = document.getElementById("term-host");
      if (sel) sel.value = host;
      activateView("terminal");
      document.getElementById("term-cmd").focus();
    },
    ping: async (host) => {
      const target = prompt("Ping to which IP?");
      if (!target) return;
      try {
        const r = await postJSON("/api/exec",
          {host, command: `ping -c 2 ${target}`});
        alert(r.output);
      } catch (e) { alert(e.message); }
    },
  };

  function showNodeInfo(node) {
    selectedEdgeId = null;
    const rows = [];
    rows.push(`<h3>${node.name}</h3>`);
    rows.push(`<div class="kind">${node.role}${node.service ? ":" + node.service : ""}</div>`);
    rows.push("<dl>");
    if (node.group) rows.push(`<dt>group</dt><dd>${node.group}</dd>`);
    rows.push(`<dt>status</dt><dd>${node.status}</dd>`);

    const ifaces = node.interfaces || [];
    if (ifaces.length) {
      rows.push(`<dt style="grid-column: 1 / -1; margin-top: 8px; color: #58a6ff;">interfaces</dt>`);
      for (const iface of ifaces) {
        rows.push(`<dt>${iface.network.replace("netlab-", "")}</dt>`);
        rows.push(`<dd>${iface.ip}/${iface.prefix || "?"} ${iface.subnet ? "(" + iface.subnet + ")" : ""}</dd>`);
        if (iface.gateway) {
          rows.push(`<dt>↳ gw</dt><dd>${iface.gateway}</dd>`);
        }
        if (iface.mac) {
          rows.push(`<dt>↳ mac</dt><dd>${iface.mac}</dd>`);
        }
      }
    }
    rows.push("</dl>");
    rows.push('<div class="field-actions">');
    rows.push(`<button class="btn btn-sm" data-action="terminal" data-host="${node.name}">Terminal</button>`);
    rows.push(`<button class="btn btn-sm" data-action="ping" data-host="${node.name}">Ping</button>`);
    if (node.status === "running") {
      rows.push(`<button class="btn btn-sm btn-danger" data-action="stop" data-host="${node.name}">Stop</button>`);
    } else {
      rows.push(`<button class="btn btn-sm btn-primary" data-action="start" data-host="${node.name}">Start</button>`);
    }
    rows.push(`<button class="btn btn-sm" data-action="logs" data-host="${node.name}">Logs</button>`);
    rows.push("</div>");
    rows.push('<pre id="mon-log" class="log" style="display:none;max-height:200px"></pre>');
    propsEl.innerHTML = rows.join("");
    propsEl.querySelectorAll("button[data-action]").forEach(b => {
      b.addEventListener("click", () => {
        const h = handlers[b.dataset.action];
        if (h) h(b.dataset.host);
      });
    });
  }

  function showEdgeInfo(edge) {
    const a = findNode(edge.source);
    const b = findNode(edge.target);
    const rows = [];
    rows.push(`<h3>${edge.network?.replace("netlab-", "") || "network"}</h3>`);
    rows.push(`<div class="kind">layer-2 connection</div>`);
    rows.push("<dl>");
    rows.push(`<dt>subnet</dt><dd>${edge.subnet || "?"}</dd>`);
    if (edge.gateway) rows.push(`<dt>gateway</dt><dd>${edge.gateway}</dd>`);
    if (a) {
      rows.push(`<dt style="grid-column: 1 / -1; margin-top: 8px; color: #58a6ff;">endpoints</dt>`);
      const aIp = (a.interfaces || []).find(i => i.network === edge.network);
      rows.push(`<dt>${a.label}</dt><dd>${aIp ? aIp.ip : "?"}</dd>`);
    }
    if (b) {
      const bIp = (b.interfaces || []).find(i => i.network === edge.network);
      rows.push(`<dt>${b.label}</dt><dd>${bIp ? bIp.ip : "?"}</dd>`);
    }
    rows.push("</dl>");
    rows.push('<p class="muted" style="font-size: 11px; margin-top: 12px;">Both endpoints share this Docker bridge — ping works at layer 2 with no routing.</p>');
    propsEl.innerHTML = rows.join("");
  }

  // ---------- network sidebar ----------

  function renderNetworkList(data) {
    if (!netlistEl) return;
    const nets = data.networks || [];
    if (!nets.length) {
      netlistEl.innerHTML = '<p class="muted" style="padding: 12px; font-size: 12px;">no networks yet</p>';
      return;
    }
    const html = nets.map(n => `
      <div class="net-item" data-net="${n.name}">
        <div class="net-name">${n.name.replace("netlab-", "")}</div>
        <div class="net-subnet">${n.subnet || "?"}</div>
        <div class="net-count">${(n.members || []).length} container(s)</div>
      </div>
    `).join("");
    netlistEl.innerHTML = html;
    netlistEl.querySelectorAll(".net-item").forEach(item => {
      item.addEventListener("click", () => {
        const netName = item.dataset.net;
        const meta = nets.find(x => x.name === netName);
        if (meta) showNetworkInfo(meta);
      });
    });
  }

  function showNetworkInfo(meta) {
    const rows = [];
    rows.push(`<h3>${meta.name.replace("netlab-", "")}</h3>`);
    rows.push(`<div class="kind">docker bridge</div>`);
    rows.push("<dl>");
    rows.push(`<dt>subnet</dt><dd>${meta.subnet || "?"}</dd>`);
    if (meta.gateway) rows.push(`<dt>gateway</dt><dd>${meta.gateway}</dd>`);
    if (meta.driver) rows.push(`<dt>driver</dt><dd>${meta.driver}</dd>`);
    if (meta.id) rows.push(`<dt>id</dt><dd>${meta.id}</dd>`);
    rows.push(`</dl>`);
    if (meta.members && meta.members.length) {
      rows.push(`<h4 style="margin-top: 16px;">members</h4>`);
      rows.push(`<ul class="member-list">`);
      for (const m of meta.members) {
        rows.push(`<li>${m.replace("netlab-", "")}</li>`);
      }
      rows.push(`</ul>`);
    }
    propsEl.innerHTML = rows.join("");
  }

  // ---------- drag ----------

  function makeDragHandler(id) {
    return (evt) => {
      evt.stopPropagation();
      evt.preventDefault();
      const p = positions[id];
      if (!p) return;
      const sp = svgPoint(evt);
      drag = {id, dx: sp.x - p.x, dy: sp.y - p.y};
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    };
  }

  function onMove(evt) {
    if (!drag) return;
    const sp = svgPoint(evt);
    positions[drag.id] = {x: sp.x - drag.dx, y: sp.y - drag.dy};
    refresh();
  }

  function onUp() {
    drag = null;
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  }

  // ---------- zoom/pan ----------

  function onWheel(evt) {
    evt.preventDefault();
    const f = Math.exp(-evt.deltaY * 0.0015);
    const newS = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, view.s * f));
    const rect = svgEl.getBoundingClientRect();
    const mx = evt.clientX - rect.left, my = evt.clientY - rect.top;
    view.x = mx - (mx - view.x) * (newS / view.s);
    view.y = my - (my - view.y) * (newS / view.s);
    view.s = newS;
    applyView();
  }

  function onPanStart(evt) {
    if (evt.target !== svgEl && evt.target.parentNode !== svgEl) return;
    const rect = svgEl.getBoundingClientRect();
    panning = {
      startX: evt.clientX - rect.left, startY: evt.clientY - rect.top,
      viewX: view.x, viewY: view.y,
    };
    document.addEventListener("mousemove", onPanMove);
    document.addEventListener("mouseup", onPanEnd);
  }

  function onPanMove(evt) {
    if (!panning) return;
    const rect = svgEl.getBoundingClientRect();
    view.x = panning.viewX + (evt.clientX - rect.left) - panning.startX;
    view.y = panning.viewY + (evt.clientY - rect.top) - panning.startY;
    applyView();
  }

  function onPanEnd() {
    panning = null;
    document.removeEventListener("mousemove", onPanMove);
    document.removeEventListener("mouseup", onPanEnd);
  }

  function resetZoom() { view.x = 0; view.y = 0; view.s = 1; applyView(); }
  function zoomBy(f) {
    view.s = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, view.s * f));
    applyView();
  }

  // ---------- validation ----------

  async function runValidation() {
    const btn = document.getElementById("mon-validate");
    if (btn) { btn.disabled = true; btn.textContent = "Testing…"; }
    try {
      const r = await postJSON("/api/validate", {});
      lastValidation = r;
      showValidationResults(r);
    } catch (e) {
      propsEl.innerHTML = `<p class="muted">Validation error: ${e.message}</p>`;
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Validate"; }
    }
  }

  function showValidationResults(r) {
    const rows = [];
    rows.push(`<h3>Connectivity</h3>`);
    const s = r.summary;
    const color = s.failed === 0 ? "#3fb950" : "#f85149";
    rows.push(`<div class="kind" style="color: ${color};">${s.passed}/${s.total} passed</div>`);
    if (!r.tests || !r.tests.length) {
      rows.push('<p class="muted">No tests ran (need at least 2 containers on a network).</p>');
    } else {
      rows.push('<table class="calc-table" style="font-size: 11px;">');
      rows.push('<thead><tr><th>from</th><th>to</th><th>rtt</th></tr></thead><tbody>');
      for (const t of r.tests) {
        const ok = t.ok ? "✓" : "✗";
        const color = t.ok ? "#3fb950" : "#f85149";
        rows.push(`<tr>
          <td style="color: ${color};">${ok} ${t.from.replace("netlab-", "")}</td>
          <td>${t.to.replace("netlab-", "")}</td>
          <td class="mono">${t.ok ? t.rtt_ms + "ms" : "—"}</td>
        </tr>`);
      }
      rows.push('</tbody></table>');
    }
    propsEl.innerHTML = rows.join("");
  }

  // ---------- public ----------

  async function refresh() {
    svgEl = document.getElementById("monitor-svg");
    propsEl = document.getElementById("monitor-props");
    netlistEl = document.getElementById("monitor-netlist");
    if (!svgEl || !propsEl) return;
    let data;
    try {
      data = await api("/api/graph");
    } catch (e) {
      svgEl.innerHTML = "";
      propsEl.innerHTML = `<p class="muted">${e.message}</p>`;
      return;
    }
    lastData = data;
    const clusterSig = (data.nodes || []).map(n => n.name).sort().join(",");
    if (clusterSig !== lastCluster) {
      resetPositions();
      lastCluster = clusterSig;
    }
    layoutAll(data);
    drawBackground();
    const vp = svgEl.querySelector("#monitor-viewport");

    // draw group boxes
    const boxes = [];
    const groups = data.groups || [];
    const gw = 340, gh = 440, gap = 24, rowMax = 3;
    let x = 24, y = 24, col = 0;
    for (const g of groups) {
      if (col >= rowMax) { col = 0; x = 24; y += gh + gap; }
      boxes.push({x, y, w: gw, h: gh,
                  name: g.name, subnet: g.subnet,
                  type: g.type, host_count: g.host_count});
      x += gw + gap; col++;
    }
    drawBoxes(boxes);

    // draw real edges
    drawEdges(data.edges || []);

    // draw virtual centrals for bus/star without device
    for (const g of groups) {
      const devices = data.nodes.filter(n =>
        ["switch","hub","ap"].includes(n.role) && n.group === g.name);
      if (["bus","star"].includes(g.type) && devices.length === 0) {
        const key = `__central__${g.name}`;
        if (positions[key]) {
          drawNode({
            name: key, label: g.type, role: "central",
            interfaces: [{network: `netlab-${g.name}`,
                          ip: `<${g.type}>`}],
          }, true);
        }
      }
    }

    // draw all nodes
    for (const n of data.nodes) drawNode(n, false);

    renderNetworkList(data);
    applyView();
  }

  function init() {
    const svg = document.getElementById("monitor-svg");
    if (svg) {
      svg.addEventListener("wheel", onWheel, {passive: false});
      svg.addEventListener("mousedown", onPanStart);
    }
    const zi = document.getElementById("mon-zoom-in");
    const zo = document.getElementById("mon-zoom-out");
    const zr = document.getElementById("mon-zoom-reset");
    if (zi) zi.onclick = () => zoomBy(1.25);
    if (zo) zo.onclick = () => zoomBy(0.8);
    if (zr) zr.onclick = resetZoom;
    const v = document.getElementById("mon-validate");
    if (v) v.onclick = runValidation;
  }

  window.NetLabMonitor = {init, refresh};
})();