"use strict";

(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  let svgEl, propsEl, netlistEl;
  const view = {x: 0, y: 0, s: 1};
  let viewport, nodesData = [], edgesData = [], groupsData = [];
  const positions = {};
  let drag = null, panning = null;
  let isRendering = false;
  let activeTrafficData = {};
  let packets = []; 
  let animFrame = null;

  function el(tag, attrs = {}) { const e = document.createElementNS(SVG_NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; }
  function applyView() { if (viewport) viewport.setAttribute("transform", `translate(${view.x}, ${view.y}) scale(${view.s})`); }
  function svgPoint(evt) { const pt = svgEl.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY; const p = pt.matrixTransform(svgEl.getScreenCTM().inverse()); return { x: (p.x - view.x) / view.s, y: (p.y - view.y) / view.s }; }

  function onWheel(evt) {
    evt.preventDefault();
    const factor = Math.exp(-evt.deltaY * 0.0015);
    const newS = Math.max(0.2, Math.min(3, view.s * factor));
    const rect = svgEl.getBoundingClientRect();
    const mx = evt.clientX - rect.left, my = evt.clientY - rect.top;
    view.x = mx - (mx - view.x) * (newS / view.s);
    view.y = my - (my - view.y) * (newS / view.s);
    view.s = newS; applyView();
  }

  function onPanStart(evt) {
    if (evt.button !== 0 || (evt.target !== svgEl && evt.target.parentNode !== svgEl)) return;
    const rect = svgEl.getBoundingClientRect();
    const start = { x: evt.clientX - rect.left, y: evt.clientY - rect.top, vx: view.x, vy: view.y };
    const move = (me) => { view.x = start.vx + (me.clientX - rect.left) - start.x; view.y = start.vy + (me.clientY - rect.top) - start.y; applyView(); };
    const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  }

  // ================== REAL TOPOLOGY LAYOUT ENGINE ==================
  function calculateLayout() {
    Object.keys(positions).forEach(k => delete positions[k]);
    
    const startX = 250, startY = 250;
    const colWidth = 400, rowHeight = 400;

    // 1. چیدمان گروه‌ها بر اساس شکل هندسی
    groupsData.forEach((g, i) => {
        const col = i % 3;
        const row = Math.floor(i / 3);
        const cx = startX + col * colWidth;
        const cy = startY + row * rowHeight;
        
        const hosts = nodesData.filter(n => n.group === g.name && n.role === "host");
        const central = nodesData.find(n => n.group === g.name && ["switch","hub","ap","modem"].includes(n.role));
        
        if (g.type === "ring" && hosts.length > 0) {
            // حلقه: هاست‌ها دور یک دایره
            const radius = Math.max(80, hosts.length * 15);
            hosts.forEach((h, j) => {
                const angle = (j / hosts.length) * 2 * Math.PI;
                positions[h.name] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
            });
        } else if (g.type === "star" && hosts.length > 0) {
            // ستاره: دستگاه مرکزی در وسط، هاست‌ها دور آن
            const radius = 90;
            if (central) positions[central.name] = {x: cx, y: cy};
            hosts.forEach((h, j) => {
                const angle = (j / hosts.length) * 2 * Math.PI;
                positions[h.name] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
            });
        } else if (g.type === "bus") {
            // خطی: هاست‌ها در یک خط افقی
            const startBX = cx - (hosts.length * 40) / 2;
            hosts.forEach((h, j) => {
                positions[h.name] = { x: startBX + j * 40, y: cy };
            });
        } else {
            // سوییچ/هاب: مرکز در بالا، هاست‌ها در شبکه
            if (central) positions[central.name] = {x: cx, y: cy - 60};
            hosts.forEach((h, j) => {
                const r = Math.floor(j / 3);
                const c = j % 3;
                positions[h.name] = { x: cx - 40 + c * 40, y: cy + 20 + r * 50 };
            });
        }
    });
    
    // 2. چیدمان روترها (بین گروه‌هایی که به آن‌ها وصل هستند)
    const routers = nodesData.filter(n => n.role === "router");
    routers.forEach(r => {
        const connectedNets = edgesData.filter(e => e.source === r.name || e.target === r.name).map(e => e.network);
        let sumX = 0, sumY = 0, count = 0;
        
        connectedNets.forEach(net => {
            const g = groupsData.find(g => net.includes(g.name));
            if (g) {
                const gIndex = groupsData.indexOf(g);
                const col = gIndex % 3;
                const row = Math.floor(gIndex / 3);
                sumX += startX + col * colWidth;
                sumY += startY + row * rowHeight;
                count++;
            }
        });
        
        if (count > 0) {
            positions[r.name] = { x: sumX / count + 200, y: sumY / count - 50 };
        } else {
            positions[r.name] = { x: 100, y: 100 };
        }
    });
  }
  // ================================================================

  function initPackets() {
    packets = [];
    for (const e of edgesData) {
        if (activeTrafficData[e.source] || activeTrafficData[e.target]) {
            packets.push({
                source: e.source, target: e.target,
                progress: Math.random(),
                speed: 0.005 + (Math.random() * 0.01)
            });
        }
    }
  }

  function animate() {
    if (!viewport) return;
    viewport.querySelectorAll(".packet-dot").forEach(p => p.remove());

    for (const p of packets) {
        const a = positions[p.source], b = positions[p.target];
        if (!a || !b) continue;

        p.progress += p.speed;
        if (p.progress > 1) p.progress = 0;

        const cx = a.x + (b.x - a.x) * p.progress;
        const cy = a.y + (b.y - a.y) * p.progress;

        const dot = el("circle", { cx: cx, cy: cy, r: 5, fill: "#ff003c", class: "packet-dot", filter: "drop-shadow(0 0 4px #ff003c)" });
        viewport.appendChild(dot);
    }
    animFrame = requestAnimationFrame(animate);
  }

  function showNodeInfo(node) {
    const rows = [`<h3>${node.name}</h3>`, `<div class="kind">${node.role.toUpperCase()}</div>`, "<dl>"];
    if (node.group) rows.push(`<dt>Group</dt><dd>${node.group}</dd>`);
    rows.push(`<dt>Status</dt><dd>${node.status}</dd>`);
    for (const [net, ip] of Object.entries(node.ips || {})) {
      rows.push(`<dt>${net.replace("netlab-", "")}</dt><dd>${ip}</dd>`);
    }
    rows.push("</dl>");

    rows.push(`<div class="field" style="margin-top:15px;">`);
    rows.push(`<label>Bandwidth Limit (Mbps)</label>`);
    rows.push(`<div style="display:flex; gap:5px; margin-top:5px;">`);
    rows.push(`<input type="number" id="bw-input-${node.name}" value="0" style="width:70px; padding:4px;">`);
    rows.push(`<button class="btn btn-sm" onclick="window.applyBandwidth('${node.name}')">Apply</button>`);
    rows.push(`</div></div>`);

    if (node.role === "host" || node.role === "router") {
        rows.push(`<div class="field" style="margin-top:15px; border-top:1px solid #30363d; padding-top:10px;">`);
        rows.push(`<button class="btn btn-sm btn-primary" style="width:100%; margin-top:5px;" onclick="window.startTrafficTo('${node.name}')">Start Traffic</button>`);
        rows.push(`</div>`);
    }
    propsEl.innerHTML = rows.join("");
  }

  window.applyBandwidth = async function(name) {
    const val = parseInt(document.getElementById(`bw-input-${name}`).value);
    try {
        await postJSON(`/api/container/${name}/bandwidth`, { limit: val });
        alert("Bandwidth updated in Docker!");
    } catch(e) { alert("Error: " + e.message); }
  };

  window.startTrafficTo = async function(sourceName) {
    const targetName = prompt("Enter target container name (e.g. netlab-grpA-host2):");
    if (!targetName) return;
    try {
      await postJSON("/api/traffic/start", { source: sourceName, target: targetName });
      await draw(); 
    } catch (e) { alert("Error: " + e.message); }
  };

  function startNodeDrag(evt, n) {
    evt.stopPropagation();
    const p = svgPoint(evt);
    drag = { id: n.name, dx: p.x - (positions[n.name]?.x || 0), dy: p.y - (positions[n.name]?.y || 0) };
    document.addEventListener("mousemove", onNodeDrag);
    document.addEventListener("mouseup", onNodeDrop);
  }
  function onNodeDrag(evt) {
    if (!drag) return;
    const p = svgPoint(evt);
    positions[drag.id] = { x: p.x - drag.dx, y: p.y - drag.dy };
    draw();
  }
  function onNodeDrop() {
    drag = null;
    document.removeEventListener("mousemove", onNodeDrag);
    document.removeEventListener("mouseup", onNodeDrop);
  }

  async function draw() {
    if (!viewport || isRendering) return;
    isRendering = true;
    
    try {
        try {
            const t = await api("/api/traffic/status");
            activeTrafficData = t.active || {};
        } catch(e) {}

        viewport.innerHTML = "";
        
        for (const e of edgesData) {
          const a = positions[e.source], b = positions[e.target];
          if (a && b) {
            let edgeClass = "edge edge-lan";
            if (activeTrafficData[e.source] || activeTrafficData[e.target]) {
                edgeClass += " edge-traffic"; 
            }
            viewport.appendChild(el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: edgeClass}));
          }
        }

        for (const n of nodesData) {
          const p = positions[n.name];
          if (!p) continue;
          const g = el("g", {class: "node-group node-" + n.role, transform: `translate(${p.x}, ${p.y})`});
          g.style.cursor = "pointer";
          g.appendChild(el("circle", {cx: 0, cy: 0, r: 18, class: "device-body"}));
          const lbl = el("text", {x: 0, y: 32, class: "node-label"}); lbl.textContent = n.label; g.appendChild(lbl);
          
          const ips = Object.values(n.ips || {});
          if (ips.length > 0) {
            const ipL = el("text", {x: 0, y: 44, class: "node-ip-label"}); ipL.textContent = ips[0]; g.appendChild(ipL);
          }

          g.addEventListener("mousedown", (evt) => startNodeDrag(evt, n));
          g.addEventListener("click", (evt) => { evt.stopPropagation(); showNodeInfo(n); });
          viewport.appendChild(g);
        }
        
        initPackets();
    } finally {
        isRendering = false;
    }
  }

  async function refresh() {
    svgEl = document.getElementById("monitor-svg");
    propsEl = document.getElementById("monitor-props");
    netlistEl = document.getElementById("monitor-netlist");
    if (!svgEl || !propsEl) return;

    try {
      const data = await api("/api/graph");
      if (!data.nodes || !data.nodes.length) {
        propsEl.innerHTML = '<p class="muted">No containers. Deploy a cluster.</p>';
        if (netlistEl) netlistEl.innerHTML = '';
        svgEl.innerHTML = "";
        return;
      }
      
      nodesData = data.nodes;
      edgesData = data.edges || [];
      groupsData = data.groups || [];

      calculateLayout();

      while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
      viewport = el("g");
      svgEl.appendChild(viewport);
      
      await draw();
      applyView();

      if (netlistEl) {
        netlistEl.innerHTML = (data.networks || []).map(net => `
          <div class="net-item">
            <div class="net-name">${net.name.replace("netlab-", "")}</div>
            <div class="net-subnet">${net.subnet || "?"}</div>
          </div>`).join("");
      }
    } catch (e) {
      console.error(e);
      propsEl.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
    }
  }

  function init() {
    const svg = document.getElementById("monitor-svg");
    if (svg) { 
      svg.addEventListener("wheel", onWheel, {passive: false}); 
      svg.addEventListener("mousedown", onPanStart); 
    }
    document.getElementById("mon-zoom-in").onclick = () => { view.s *= 1.2; applyView(); };
    document.getElementById("mon-zoom-out").onclick = () => { view.s *= 0.8; applyView(); };
    document.getElementById("mon-zoom-reset").onclick = () => { view.x=0; view.y=0; view.s=1; applyView(); };
    
    document.getElementById("traffic-global-start").onclick = async () => {
        try { 
            await postJSON("/api/traffic/start_global", {}); 
            await draw(); 
        } catch (e) { alert(e.message); }
    };
    
    document.getElementById("traffic-global-stop").onclick = async () => {
        try { 
            await postJSON("/api/traffic/stop_all", {}); 
            activeTrafficData = {};
            await draw(); 
        } catch (e) { alert(e.message); }
    };

    document.getElementById("mon-fullscreen").onclick = () => {
      const viewEl = document.getElementById("view-monitor");
      viewEl.classList.toggle("fullscreen");
      const isFull = viewEl.classList.contains("fullscreen");
      document.getElementById("mon-fullscreen").textContent = isFull ? "✕" : "⛶";
    };

    if (animFrame) cancelAnimationFrame(animFrame);
    animate();

    setInterval(() => {
        if (document.getElementById("view-monitor").classList.contains("active") && viewport) {
            draw();
        }
    }, 3000);
  }

  window.NetLabMonitor = {init, refresh};
})();