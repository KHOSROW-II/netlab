"use strict";

(function () {
  function row(label, value) {
    return `<dt>${label}</dt><dd>${value}</dd>`;
  }

  function renderIPv4(f) {
    return `
      <h3>${f.address}</h3>
      <div class="kind">IPv4 ${f.ip_class ? "class " + f.ip_class : ""}</div>
      <dl>
        ${row("Subnet", f.subnet)}
        ${row("Prefix", "/" + f.prefix_length)}
        ${row("Netmask", f.netmask)}
        ${row("Network", f.network_address)}
        ${row("Broadcast", f.broadcast_address)}
        ${row("Host range", f.first_usable + " – " + f.last_usable)}
        ${row("Total addresses", f.total_addresses)}
        ${row("Usable hosts", f.usable_hosts)}
        ${row("Host bits", f.host_bits_count)}
        ${row("In subnet", f.address_in_subnet ? "yes" : "NO")}
      </dl>
      <h4>Binary</h4>
      <pre class="log mono">${f.binary_address}
${f.binary_netmask}
${f.network_bits.padEnd(32).replace(/[^ ]/g, " ")}${"".padEnd(0)}
network:   ${f.binary_network}
broadcast: ${f.binary_broadcast}</pre>
    `;
  }

  function renderIPv6(f) {
    return `
      <h3>${f.address}</h3>
      <div class="kind">IPv6</div>
      <dl>
        ${row("Subnet", f.subnet)}
        ${row("Prefix", "/" + f.prefix_length)}
        ${row("Network", f.network_address)}
        ${row("Last address", f.last_address)}
        ${row("Host bits", f.host_bits_count)}
        ${row("Hex", f.hex_address)}
        ${row("Interface ID", f.interface_id || "—")}
        ${row("In subnet", f.address_in_subnet ? "yes" : "NO")}
      </dl>
    `;
  }

  async function analyze() {
    const ip = document.getElementById("calc-ip").value.trim();
    const subnet = document.getElementById("calc-subnet").value.trim();
    const out = document.getElementById("calc-result");
    if (!ip) return;
    out.innerHTML = '<p class="muted">Analyzing…</p>';
    try {
      const r = await postJSON("/api/subnet/analyze", {ip, subnet});
      out.innerHTML = r.kind === "ipv6"
        ? renderIPv6(r.fields)
        : renderIPv4(r.fields);
    } catch (e) {
      out.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
    }
  }

  async function split() {
    const subnet = document.getElementById("calc-split-subnet").value.trim();
    const mode = document.getElementById("calc-split-mode").value;
    const value = document.getElementById("calc-split-value").value.trim();
    const out = document.getElementById("calc-split-result");
    if (!subnet || !value) {
      out.innerHTML = '<p class="muted">Provide subnet and value.</p>';
      return;
    }
    out.innerHTML = '<p class="muted">Splitting…</p>';
    const body = {subnet};
    if (mode === "count") body.count = parseInt(value);
    else body.prefix = parseInt(value);
    try {
      const r = await postJSON("/api/subnet/split", body);
      if (!r.subnets.length) {
        out.innerHTML = '<p class="muted">No subnets produced.</p>';
        return;
      }
      const rows = r.subnets.map((s, i) => `
        <tr>
          <td>${i + 1}</td>
          <td class="mono">${s.network}</td>
          <td class="mono">${s.netmask}</td>
          <td class="mono">${s.first_usable} – ${s.last_usable}</td>
          <td class="mono">${s.broadcast}</td>
          <td>${s.usable_hosts}</td>
        </tr>`).join("");
      out.innerHTML = `
        <h3>${r.subnets.length} subnet(s)</h3>
        <table class="calc-table">
          <thead>
            <tr><th>#</th><th>Network</th><th>Mask</th>
                <th>Host range</th><th>Broadcast</th><th>Hosts</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    } catch (e) {
      out.innerHTML = `<p class="muted">Error: ${e.message}</p>`;
    }
  }

  function bind() {
    const a = document.getElementById("calc-analyze");
    const s = document.getElementById("calc-split");
    if (a) a.onclick = analyze;
    if (s) s.onclick = split;
    const ip = document.getElementById("calc-ip");
    if (ip) ip.addEventListener("keydown", (e) => {
      if (e.key === "Enter") analyze();
    });
  }

  document.addEventListener("DOMContentLoaded", bind);
})();