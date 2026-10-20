"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
}

function setBanner(text, isWarn, canFix) {
  const b = $("routing-banner");
  if (!text) { b.hidden = true; return; }
  b.hidden = false;
  b.className = "banner " + (isWarn ? "banner-warn" : "banner-ok");
  $("routing-banner-text").textContent = text;
  $("routing-banner-fix").hidden = !canFix;
}

async function refreshRouting() {
  try {
    const r = await api("/api/routing");
    if (!r.needed) { setBanner("", false, false); return; }
    setBanner(
      r.enabled
        ? "Routing OK · br_netfilter disabled"
        : "Routing BLOCKED · br_netfilter enabled — click Try fix",
      !r.enabled, r.can_fix,
    );
  } catch (e) {
    setBanner("Routing unknown · " + e.message, true, false);
  }
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("topbar-status").textContent = s.cluster === "(none)"
      ? "no cluster" : `cluster · ${s.cluster}`;
    const sel = $("term-host");
    const cur = sel.value;
    let html = "";
    for (const g of s.groups) {
      html += `<optgroup label="${g.name}">`;
      for (const c of g.containers) {
        html += `<option value="${c.name}">${c.label}</option>`;
      }
      html += "</optgroup>";
    }
    if (s.placeholders && s.placeholders.length) {
      html += '<optgroup label="Devices">';
      for (const c of s.placeholders) {
        html += `<option value="${c.name}">${c.label}</option>`;
      }
      html += "</optgroup>";
    }
    if (s.routers.length) {
      html += '<optgroup label="Routers">';
      for (const c of s.routers) {
        html += `<option value="${c.name}">${c.label}</option>`;
      }
      html += "</optgroup>";
    }
    if (s.services.length) {
      html += '<optgroup label="Services">';
      for (const c of s.services) {
        html += `<option value="${c.name}">${c.label}</option>`;
      }
      html += "</optgroup>";
    }
    sel.innerHTML = html;
    if (cur && sel.querySelector(`option[value="${cur}"]`)) sel.value = cur;
  } catch (_) {}
}

async function fixRouting() {
  try {
    const r = await postJSON("/api/routing/enable", {});
    setBanner(
      r.enabled
        ? "Routing OK · br_netfilter disabled"
        : "Routing still blocked · " + (r.hint || "run as root"),
      !r.enabled, true,
    );
  } catch (e) {
    setBanner("Routing fix failed · " + e.message, true, true);
  }
}

function activateView(name) {
  document.querySelectorAll(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach(el => {
    el.classList.toggle("active", el.id === `view-${name}`);
  });
  if (name === "monitor" && window.NetLabMonitor) {
    window.NetLabMonitor.refresh();
  }
}

async function doTerminal() {
  const host = $("term-host").value;
  const cmd = $("term-cmd").value.trim();
  if (!host || !cmd) return;
  const out = $("term-output");
  out.textContent = `[${host}] $ ${cmd}\n…`;
  try {
    const r = await postJSON("/api/exec", {host, command: cmd});
    out.textContent = `[${host}] $ ${cmd}\n${r.output}\n[exit ${r.code}]`;
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
  }
}

async function doDiagnostics(fix) {
  const out = $("diag-output");
  out.textContent = fix ? "Checking and fixing…" : "Checking…";
  try {
    const r = await postJSON("/api/doctor", {fix, file: null});
    out.textContent = r.output || "(no output)";
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
  }
}

function bindGlobal() {
  document.querySelectorAll(".nav-item").forEach(el => {
    el.addEventListener("click", () => activateView(el.dataset.view));
  });
  $("routing-banner-fix").onclick = fixRouting;
  $("routing-banner-dismiss").onclick = () => setBanner("", false, false);
  $("term-run").onclick = doTerminal;
  $("term-cmd").addEventListener("keydown", e => {
    if (e.key === "Enter") doTerminal();
  });
  $("diag-check").onclick = () => doDiagnostics(false);
  $("diag-fix").onclick = () => doDiagnostics(true);
  $("mon-refresh").onclick = () => window.NetLabMonitor && window.NetLabMonitor.refresh();
  $("mon-destroy").onclick = async () => {
    if (!confirm(
      "Remove ALL netlab-* containers and networks (any cluster)?\n" +
      "This is a full reset."
    )) return;
    try {
      const r = await postJSON("/api/destroy", {});
      const c = r.cleanup || {};
      const msg = `Removed ${c.containers || 0} containers, ` +
                  `${c.networks || 0} networks.`;
      await refreshStatus();
      await refreshRouting();
      if (window.NetLabMonitor) window.NetLabMonitor.refresh();
      // Surface result in the editor status bar if visible
      const es = document.getElementById("editor-status");
      if (es) {
        es.textContent = msg;
        es.className = "statusbar ok";
      }
    } catch (e) {
      alert("Destroy failed: " + e.message);
    }
  };
}

document.addEventListener("DOMContentLoaded", () => {
  // Splash screen removal logic
  setTimeout(() => {
    const splash = document.getElementById("splash-screen");
    if (splash) {
      splash.classList.add("hidden");
      setTimeout(() => splash.remove(), 800); // remove from DOM after fade
    }
  }, 1500); // Show splash for 1.5 seconds

  bindGlobal();
  refreshStatus();
  refreshRouting();
  if (window.NetLabEditor) window.NetLabEditor.init();
  if (window.NetLabMonitor) window.NetLabMonitor.init();
  setInterval(refreshStatus, 5000);
  setInterval(refreshRouting, 10000);
  setInterval(() => {
    if ($("view-monitor").classList.contains("active")) {
      window.NetLabMonitor && window.NetLabMonitor.refresh();
    }
  }, 5000);
});