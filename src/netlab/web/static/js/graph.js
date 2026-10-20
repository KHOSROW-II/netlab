"use strict";

/* Simple deterministic grouped-column layout for the topology graph. */

function layoutGraph(data) {
  const W = 1000, H = 560;
  const COL = 170, GAP = 40, TOP = 70, ROW = 46;
  const positions = {};
  const groupsBoxes = [];

  const groups = data.groups || [];
  const routers = data.nodes.filter(n => n.role === "router");
  const services = data.nodes.filter(n => n.role === "service");
  const hostsByGroup = {};
  for (const n of data.nodes) {
    if (n.role === "host" && n.group) {
      (hostsByGroup[n.group] = hostsByGroup[n.group] || []).push(n);
    }
  }

  let x = 40;
  for (const g of groups) {
    const hosts = (hostsByGroup[g.name] || []).sort((a, b) => a.name.localeCompare(b.name));
    const groupServices = services.filter(s => s.group === g.name);
    const rows = Math.max(hosts.length, groupServices.length) || 1;
    const colHeight = rows * ROW + 40;
    let y = TOP;
    for (const h of hosts) {
      positions[h.name] = { x: x + COL / 2, y };
      y += ROW;
    }
    for (const s of groupServices) {
      positions[s.name] = { x: x + COL / 2, y };
      y += ROW;
    }
    groupsBoxes.push({
      name: g.name, x, y: TOP - 20, w: COL, h: colHeight,
      subnet: g.subnet, type: g.type,
    });
    x += COL + GAP;
  }

  if (routers.length) {
    const rx = x + COL / 2;
    const ry = TOP + 80;
    for (let i = 0; i < routers.length; i++) {
      positions[routers[i].name] = { x: rx, y: ry + i * ROW };
    }
    x += COL + GAP;
  }

  return { positions, groupsBoxes, width: Math.max(x + 40, W), height: H };
}

function clearSvg(svg) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
}

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) {
    el.setAttribute(k, v);
  }
  return el;
}

function renderGraph(svg, data, onNodeClick) {
  clearSvg(svg);
  const { positions, groupsBoxes, width, height } = layoutGraph(data);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const edgesGroup = svgEl("g", { class: "edges" });
  const nodesGroup = svgEl("g", { class: "nodes" });
  const boxesGroup = svgEl("g", { class: "boxes" });

  for (const box of groupsBoxes) {
    const rect = svgEl("rect", {
      x: box.x, y: box.y, width: box.w, height: box.h,
      rx: 6, ry: 6,
      fill: "none", stroke: "#30363d", "stroke-dasharray": "4 4",
    });
    boxesGroup.appendChild(rect);
    const label = svgEl("text", {
      x: box.x + 8, y: box.y - 6,
      "font-size": "11", "font-family": "monospace",
      fill: "#8b949e", "text-anchor": "start",
    });
    label.textContent = `${box.name}  ${box.subnet}  (${box.type})`;
    boxesGroup.appendChild(label);
  }

  for (const e of data.edges) {
    const a = positions[e.source], b = positions[e.target];
    if (!a || !b) continue;
    const line = svgEl("line", {
      x1: a.x, y1: a.y, x2: b.x, y2: b.y,
      class: `edge edge-${e.kind}`,
    });
    edgesGroup.appendChild(line);
  }

  for (const n of data.nodes) {
    const p = positions[n.name];
    if (!p) continue;
    const g = svgEl("g", {
      class: `node-group node-${n.role} node-status-${n.status}`,
      "data-id": n.name,
      transform: `translate(${p.x}, ${p.y})`,
    });
    const r = n.role === "host" ? 12 : n.role === "router" ? 14 : 10;
    const circle = svgEl("circle", { cx: 0, cy: 0, r });
    g.appendChild(circle);
    const text = svgEl("text", { x: 0, y: r + 14 });
    text.textContent = n.label;
    g.appendChild(text);
    g.addEventListener("click", () => onNodeClick(n));
    nodesGroup.appendChild(g);
  }

  svg.appendChild(edgesGroup);
  svg.appendChild(boxesGroup);
  svg.appendChild(nodesGroup);
}

function showNodeInfo(container, node, handlers) {
  const rows = [];
  rows.push(`<h3>${node.name}</h3>`);
  rows.push("<dl>");
  rows.push(`<dt>role</dt><dd>${node.role}${node.service ? ":" + node.service : ""}</dd>`);
  if (node.group) rows.push(`<dt>group</dt><dd>${node.group}</dd>`);
  rows.push(`<dt>status</dt><dd>${node.status}</dd>`);
  for (const [net, ip] of Object.entries(node.ips || {})) {
    rows.push(`<dt>${net}</dt><dd>${ip}</dd>`);
  }
  rows.push("</dl>");
  rows.push('<div class="actions">');
  rows.push(`<button class="btn btn-sm" data-action="terminal" data-host="${node.name}">Open terminal</button>`);
  if (node.status === "running") {
    rows.push(`<button class="btn btn-sm btn-danger" data-action="stop" data-host="${node.name}">Stop</button>`);
  } else {
    rows.push(`<button class="btn btn-sm btn-primary" data-action="start" data-host="${node.name}">Start</button>`);
  }
  rows.push(`<button class="btn btn-sm" data-action="logs" data-host="${node.name}">Logs</button>`);
  rows.push("</div>");
  rows.push('<pre class="log" id="node-log-output" style="display:none"></pre>');
  container.innerHTML = rows.join("");

  container.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      const host = btn.dataset.host;
      if (handlers[action]) handlers[action](host);
    });
  });
}