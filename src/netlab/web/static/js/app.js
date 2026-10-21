"use strict";

window.onerror = function (msg, url, line, col, error) {
  console.error(`[FATAL ERROR] ${msg}\nLocation: ${url}:${line}:${col}`);
  return false;
};

const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  try {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(`${res.status}: ${detail}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`[API ERROR] ${path}`, err);
    throw err;
  }
}

function postJSON(path, body) {
  return api(path, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
}

function setBanner(text, isWarn, canFix) {
  const b = $("routing-banner");
  const txt = $("routing-banner-text");
  const btnFix = $("routing-banner-fix");
  if (!b || !txt || !btnFix) return;
  
  if (!text) { b.hidden = true; return; }
  b.hidden = false;
  b.className = "banner " + (isWarn ? "banner-warn" : "banner-ok");
  txt.textContent = text;
  btnFix.hidden = !canFix;
}

async function refreshRouting() {
  try {
    const r = await api("/api/routing");
    if (!r.needed) { setBanner("", false, false); return; }
    setBanner(r.enabled ? "Routing OK (br_netfilter disabled)" : "Routing BLOCKED - click Try fix", !r.enabled, r.can_fix);
  } catch (e) { 
    setBanner("Routing status unknown", true, false); 
  }
}

async function fixRouting() {
  const btn = $("routing-banner-fix");
  const oldText = btn.textContent;
  btn.textContent = "Fixing...";
  btn.disabled = true;
  try {
    await postJSON("/api/routing/enable", {});
    await refreshRouting();
  } catch (e) {
    alert("Fix failed: " + e.message + "\n\nYou might need to run the server as root (sudo netlab web) or run the sudo command manually.");
  } finally {
    btn.textContent = oldText;
    btn.disabled = false;
  }
}

function activateView(name) {
  console.log(`[UI] Switching to view: ${name}`);
  document.querySelectorAll(".nav-item").forEach(el => el.classList.toggle("active", el.dataset.view === name));
  document.querySelectorAll(".view").forEach(el => {
    if (el.id === `view-${name}`) el.classList.add("active");
    else el.classList.remove("active");
  });
  
  if (name === "monitor" && window.NetLabMonitor) window.NetLabMonitor.refresh();
  if (name === "calculator" && window.NetLabCalculator) window.NetLabCalculator.init();
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("topbar-status").textContent = s.cluster === "(none)" ? "no cluster" : `cluster · ${s.cluster}`;
    
    const sel = $("term-host");
    if (sel) {
      const cur = sel.value;
      let html = "";
      for (const g of s.groups) {
        html += `<optgroup label="${g.name}">`;
        for (const c of g.containers) html += `<option value="${c.name}">${c.label}</option>`;
        html += "</optgroup>";
      }
      if (s.routers.length) {
        html += '<optgroup label="Routers">';
        for (const c of s.routers) html += `<option value="${c.name}">${c.label}</option>`;
        html += "</optgroup>";
      }
      sel.innerHTML = html;
      if (cur && sel.querySelector(`option[value="${cur}"]`)) sel.value = cur;
    }

    const settingsList = $("settings-list");
    if (settingsList) {
      const allNodes = [...s.groups.flatMap(g => g.containers), ...s.routers, ...s.services];
      if (!allNodes.length) {
        settingsList.innerHTML = '<p class="muted" style="padding:20px;">No devices running.</p>';
      } else {
        settingsList.innerHTML = allNodes.map(n => {
          const ipList = Object.entries(n.ips || {}).map(([net, ip]) => `${net.replace('netlab-','')}: ${ip}`).join(' | ');
          return `
            <div class="setting-row">
              <div class="info"><b>${n.label}</b> (${n.role})<span>${ipList || "No IP"}</span></div>
              <button class="btn btn-sm" onclick="document.getElementById('term-host').value='${n.name}'; window.activateView('terminal');">Terminal</button>
            </div>`;
        }).join("");
      }
    }
  } catch (e) {}
}

async function doTerminal() {
  const host = $("term-host").value;
  const cmd = $("term-cmd").value.trim();
  if (!host || !cmd) return;
  $("term-output").textContent = `[${host}] $ ${cmd}\n...`;
  try {
    const r = await postJSON("/api/exec", {host, command: cmd});
    $("term-output").textContent = `[${host}] $ ${cmd}\n${r.output}\n[exit ${r.code}]`;
  } catch (e) { $("term-output").textContent = `Error: ${e.message}`; }
}

async function doDiagnostics(fix) {
  $("diag-output").textContent = "Checking...";
  try {
    const r = await postJSON("/api/doctor", {fix, file: null});
    $("diag-output").textContent = r.output || "(no output)";
  } catch (e) { $("diag-output").textContent = `Error: ${e.message}`; }
}

window.activateView = activateView;

document.addEventListener("DOMContentLoaded", () => {
  setTimeout(() => {
    const splash = document.getElementById("splash-screen");
    if (splash) { splash.classList.add("hidden"); setTimeout(() => splash.remove(), 800); }
  }, 1500);

  document.querySelectorAll(".nav-item").forEach(el => el.addEventListener("click", () => activateView(el.dataset.view)));
  
  if ($("routing-banner-fix")) $("routing-banner-fix").onclick = fixRouting;
  if ($("routing-banner-dismiss")) $("routing-banner-dismiss").onclick = () => setBanner("", false, false);
  
  if ($("term-run")) $("term-run").onclick = doTerminal;
  if ($("diag-check")) $("diag-check").onclick = () => doDiagnostics(false);
  if ($("diag-fix")) $("diag-fix").onclick = () => doDiagnostics(true);
  if ($("set-refresh")) $("set-refresh").onclick = refreshStatus;
  
  refreshStatus(); refreshRouting();
  if (window.NetLabEditor) window.NetLabEditor.init();
  if (window.NetLabMonitor) window.NetLabMonitor.init();
  
  setInterval(refreshStatus, 5000);
  setInterval(refreshRouting, 8000);
});