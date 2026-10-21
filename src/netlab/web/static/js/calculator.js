"use strict";

(function () {
  function row(label, value) { 
    return `<dt>${label}</dt><dd>${value}</dd>`; 
  }
  
  async function analyze() {
    const ipEl = document.getElementById("calc-ip");
    const subnetEl = document.getElementById("calc-subnet");
    const out = document.getElementById("calc-result");
    if (!ipEl) return;
    
    const ip = ipEl.value.trim();
    if (!ip) {
      out.innerHTML = '<p class="muted" style="color:#f85149;">Please enter an IP address first.</p>';
      return;
    }
    const subnet = subnetEl ? subnetEl.value.trim() : "";
    
    out.innerHTML = '<p class="muted">Analyzing...</p>';
    
    try {
      const r = await postJSON("/api/subnet/analyze", {ip, subnet});
      const f = r.fields;
      out.innerHTML = `
        <h3>${f.address}</h3>
        <div class="kind">IPv4 ${f.class ? "Class " + f.class : ""}</div>
        <dl>
          ${row("Subnet", f.subnet)}
          ${row("Prefix", "/" + f.prefix)}
          ${row("Netmask", f.netmask)}
          ${row("Network", f.network)}
          ${row("Broadcast", f.broadcast)}
          ${row("Host Range", f.first + " - " + f.last)}
          ${row("Total Hosts", f.hosts)}
        </dl>
        <h4>Binary</h4>
        <pre class="log mono">${f.binary}</pre>
      `;
    } catch (e) { 
      out.innerHTML = `<p class="muted" style="color:#f85149;">Error: ${e.message}</p>`; 
    }
  }

  window.NetLabCalculator = {
    init: function() {
      const btn = document.getElementById("calc-analyze");
      if (btn && !btn.dataset.bound) {
        btn.onclick = analyze;
        // پشتیبانی از کلید Enter در فیلد IP
        const ipEl = document.getElementById("calc-ip");
        if (ipEl) ipEl.addEventListener("keydown", (e) => { if (e.key === "Enter") analyze(); });
        btn.dataset.bound = "true";
      }
    }
  };
})();