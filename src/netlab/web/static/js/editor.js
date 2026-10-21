"use strict";

console.log("[DEBUG] editor.js loaded.");

(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const ZOOM_MIN = 0.2, ZOOM_MAX = 3;

  const state = { nodes: [], edges: [], selected: null, drag: null, tool: "select" };
  const view = {x: 0, y: 0, s: 1};
  let svg, viewport, props, status, ctxMenu;

  function el(tag, attrs = {}) { const e = document.createElementNS(SVG_NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; }
  function svgPoint(evt) { const pt = svg.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse()); return { x: (p.x - view.x) / view.s, y: (p.y - view.y) / view.s }; }
  function applyView() { if (viewport) viewport.setAttribute("transform", `translate(${view.x}, ${view.y}) scale(${view.s})`); }
  function setStatus(text, kind) { status.textContent = text; status.style.color = kind === "error" ? "#f85149" : (kind === "ok" ? "#3fb950" : "var(--text-muted)"); }

  async function syncGraph() {
    try {
      const result = await postJSON("/api/editor/calculate", { nodes: state.nodes, edges: state.edges });
      state.nodes = result.nodes.map(newNode => {
        const oldNode = state.nodes.find(n => n.id === newNode.id);
        if (oldNode) { newNode.x = oldNode.x; newNode.y = oldNode.y; }
        return newNode;
      });
      render(); renderProps();
      setStatus("Topology valid.", "ok");
    } catch (err) { 
      console.error("[EDITOR] Sync failed:", err);
      setStatus(err.message, "error"); 
    }
  }

  function render() {
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    
    const defs = el("defs");
    const pat = el("pattern", {id: "grid", width: 30, height: 30, patternUnits: "userSpaceOnUse"});
    pat.appendChild(el("path", {d: "M 30 0 L 0 0 0 30", fill: "none", stroke: "#1c2128"}));
    defs.appendChild(pat); svg.appendChild(defs);
    svg.appendChild(el("rect", {x: 0, y: 0, width: "100%", height: "100%", fill: "url(#grid)"}));

    viewport = el("g");
    svg.appendChild(viewport);

    for (const e of state.edges) {
      const a = state.nodes.find(n => n.id === e.from);
      const b = state.nodes.find(n => n.id === e.to);
      if (a && b) viewport.appendChild(el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "edge edge-cable"}));
    }

    for (const n of state.nodes) {
      const g = el("g", {class: `node-group node-${n.type}`, "data-id": n.id});
      if (state.selected === n.id) g.classList.add("node-selected");

      g.appendChild(el("circle", {cx: n.x, cy: n.y, r: 24, class: "device-body"}));
      
      let d = "";
      if (n.type === "pc") d = "M8 4h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm-2 16h12m-6-4v4";
      else if (n.type === "server") d = "M3 4h18v6H3zm0 10h18v6H3zm4-7h.01M7 17h.01"; 
      else if (n.type === "switch") d = "M4 8h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2zm2 4h2m2 0h2m2 0h2";
      else if (n.type === "router") d = "M8 12h8m-4-4v8M4 12a8 8 0 1 1 16 0 8 8 0 0 1-16 0z";
      else if (n.type === "hub") d = "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6z";
      else if (n.type === "modem") d = "M4 12h16v6H4zM12 6v6m-4-4l4-4 4 4";
      
      g.appendChild(el("path", {d, class: "device-icon-svg", transform: `translate(${n.x - 12}, ${n.y - 12})`}));

      const label = el("text", {x: n.x, y: n.y + 38, class: "node-label"}); label.textContent = n.name; g.appendChild(label);
      if (n.resolved_network) { const ipL = el("text", {x: n.x, y: n.y + 52, class: "node-ip-label"}); ipL.textContent = n.resolved_network; g.appendChild(ipL); }
      if (n.resolved_ip) { const ipL = el("text", {x: n.x, y: n.y + 52, class: "node-ip-label"}); ipL.textContent = n.resolved_ip; g.appendChild(ipL); }

      g.addEventListener("mousedown", (evt) => startDrag(evt, n));
      g.addEventListener("click", (evt) => handleNodeClick(evt, n));
      g.addEventListener("contextmenu", (evt) => showNodeContext(evt, n));

      viewport.appendChild(g);
    }
    applyView();
  }

  function handleNodeClick(evt, n) {
    evt.stopPropagation();
    if (state.tool === "cable") {
      if (!state.cableStart) { state.cableStart = n.id; setStatus(`Start: ${n.name}`, "ok"); }
      else { connectNodes(state.cableStart, n.id); state.cableStart = null; setStatus("Connected.", "ok"); }
    } else { state.selected = n.id; render(); renderProps(); }
  }

  function startDrag(evt, n) {
    if (state.tool !== "select" || evt.button !== 0) return;
    evt.stopPropagation();
    const p = svgPoint(evt);
    state.drag = { id: n.id, dx: p.x - n.x, dy: p.y - n.y };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }

  function onMouseMove(evt) {
    if (!state.drag) return;
    const node = state.nodes.find(n => n.id === state.drag.id);
    if (!node) return;
    const p = svgPoint(evt); node.x = p.x - state.drag.dx; node.y = p.y - state.drag.dy; render();
  }

  function onMouseUp() { state.drag = null; document.removeEventListener("mousemove", onMouseMove); document.removeEventListener("mouseup", onMouseUp); }
  
  function connectNodes(idA, idB) { 
    if (idA === idB) return; 
    if (!state.edges.find(e => (e.from===idA && e.to===idB)||(e.from===idB && e.to===idA))) { 
      state.edges.push({ from: idA, to: idB }); 
      syncGraph(); 
    } 
  }

  function showNodeContext(evt, node) {
    evt.preventDefault(); evt.stopPropagation();
    ctxMenu.hidden = false; ctxMenu.style.left = `${evt.clientX}px`; ctxMenu.style.top = `${evt.clientY}px`;
    
    document.getElementById("ctx-connect").onclick = () => { 
      state.tool = "cable"; state.cableStart = node.id; 
      setStatus(`Start: ${node.name}`, "ok"); ctxMenu.hidden = true; 
    };
    document.getElementById("ctx-delete").onclick = () => { 
      state.nodes = state.nodes.filter(n => n.id !== node.id); 
      state.edges = state.edges.filter(e => e.from !== node.id && e.to !== node.id); 
      ctxMenu.hidden = true; syncGraph(); 
    };
  }

  function onWheel(evt) {
    evt.preventDefault(); const factor = Math.exp(-evt.deltaY * 0.0015); const newS = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, view.s * factor));
    const rect = svg.getBoundingClientRect(); const mx = evt.clientX - rect.left, my = evt.clientY - rect.top;
    view.x = mx - (mx - view.x) * (newS / view.s); view.y = my - (my - view.y) * (newS / view.s); view.s = newS; applyView();
  }

  function onPanStart(evt) {
    if (evt.button !== 0 || (evt.target !== svg && evt.target.parentNode !== svg)) return;
    const rect = svg.getBoundingClientRect(); const start = { x: evt.clientX - rect.left, y: evt.clientY - rect.top, vx: view.x, vy: view.y };
    const move = (me) => { view.x = start.vx + (me.clientX - rect.left) - start.x; view.y = start.vy + (me.clientY - rect.top) - start.y; applyView(); };
    const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  }

  async function renderProps() {
    props.innerHTML = "";
    if (!state.selected) { props.innerHTML = '<p class="muted">Select a device.</p>'; return; }
    const node = state.nodes.find(n => n.id === state.selected);
    props.innerHTML = `<h3>${node.name}</h3><div class="kind">${node.type.toUpperCase()}</div>`;
    
    if (!["pc", "router"].includes(node.type)) {
      const subnetIn = document.createElement("input"); subnetIn.value = node.subnet || "192.168.1.0/24"; subnetIn.onchange = () => { node.subnet = subnetIn.value; syncGraph(); };
      const w = document.createElement("div"); w.className = "field"; w.innerHTML = "<label>Subnet (CIDR)</label>"; w.appendChild(subnetIn); props.appendChild(w);
      if (node.resolved_network) props.innerHTML += `<div class="subnet-math-box"><div class="math-row"><span>Net:</span> <span class="mono">${node.resolved_network}</span></div><div class="math-row"><span>Mask:</span> <span class="mono">${node.resolved_mask}</span></div></div>`;
    }
  }

  function init() {
    svg = document.getElementById("editor-svg"); props = document.getElementById("editor-props"); status = document.getElementById("editor-status"); ctxMenu = document.getElementById("context-menu");
    if (!svg) return;

    svg.addEventListener("wheel", onWheel, {passive: false}); svg.addEventListener("mousedown", onPanStart);
    document.addEventListener("click", () => { if(ctxMenu) ctxMenu.hidden = true; });

    document.getElementById("tool-cable").onclick = () => { state.tool = "cable"; setStatus("Cable tool active.", "ok"); };
    document.getElementById("ed-zoom-in").onclick = () => { view.s *= 1.2; applyView(); };
    document.getElementById("ed-zoom-out").onclick = () => { view.s *= 0.8; applyView(); };
    document.getElementById("ed-zoom-reset").onclick = () => { view.x=0; view.y=0; view.s=1; applyView(); };

    document.querySelectorAll(".palette-item[data-type]").forEach(item => {
      item.addEventListener("dragstart", (e) => e.dataTransfer.setData("type", item.dataset.type));
    });
    
    svg.addEventListener("dragover", (e) => e.preventDefault());
    svg.addEventListener("drop", (e) => {
      e.preventDefault(); 
      const type = e.dataTransfer.getData("type"); 
      if (!type) return;
      
      const p = svgPoint(e);
      
      let autoSubnet = null;
      if (!["pc", "router"].includes(type)) {
          const groupCount = state.nodes.filter(n => !["pc", "router"].includes(n.type)).length;
          autoSubnet = `10.${groupCount + 10}.0.0/24`; // مثلا 10.10.0.0/24، 10.11.0.0/24
      }
      
      state.nodes.push({ 
        id: `${type}-${Date.now()}`, 
        type, 
        x: p.x, 
        y: p.y, 
        name: `${type.toUpperCase()}-${state.nodes.length+1}`, 
        subnet: autoSubnet, 
        host_count: 1 
      });
      
      syncGraph();
    });

    document.getElementById("ed-load").onchange = async (e) => {
      const path = e.target.value; if (!path) return;
      try {
        const data = await postJSON("/api/editor/load", { path });
        state.nodes = data.nodes.map(n => ({ ...n, type: n.type || n.kind })); 
        state.edges = data.edges;
        syncGraph();
        setStatus(`Loaded ${data.name}`, "ok");
      } catch (err) { setStatus("Load failed: " + err.message, "error"); }
    };

    document.getElementById("ed-deploy").onclick = async () => {
      try {
        setStatus("Deploying...", "ok");
        
        // FIX: Include "server" alongside "pc"
        const groups = state.nodes.filter(n => !["pc", "server", "router"].includes(n.type)).map(n => {
            const connectedPCs = state.nodes.filter(x => ["pc", "server"].includes(x.type) && state.edges.some(e => (e.from === x.id && e.to === n.id) || (e.to === x.id && e.from === n.id))).length;
            return { 
                name: n.name, 
                subnet: n.subnet || "192.168.1.0/24", 
                host_count: Math.max(n.host_count || 1, connectedPCs), 
                topology: n.type 
            };
        });

        const routers = state.nodes.filter(n => n.type === "router").map(n => ({ 
            name: n.name, ip_suffix: 254, 
            connects: state.edges.filter(e => e.from === n.id || e.to === n.id).map(e => state.nodes.find(x => x.id === (e.from === n.id ? e.to : e.from))).filter(x => x && !["pc", "router"].includes(x.type)).map(x => x.name) 
        }));
        
        await postJSON("/api/editor/deploy", { name: "editor", groups, routers, services: [] });
        setStatus("Deployed!", "ok");
      } catch (err) { setStatus("Deploy failed: " + err.message, "error"); }
    };

    render();
  }

  window.NetLabEditor = {init};
})();