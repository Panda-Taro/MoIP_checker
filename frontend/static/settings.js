// MoIP_checker 設定変更(WebGUI②)のクライアント側ロジック

// --- タブ切り替え ---
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "system") {
      // システム設定タブを開くたびに最新のNIC一覧を取得する(要件定義書ver1.01 3.4.4)
      loadAvailableNics();
    }
  });
});

// --- PTP設定タブ ---

// Hz⇔config.json保存形式(log2 interval)の変換(要件定義書ver1.01 3.4.4)
// interval = log2(1/Hz)、Hz = 2^(-interval)。config.json自体はinterval形式のまま(後方互換)。
function intervalToHz(interval) {
  return Math.pow(2, -interval);
}

function isValidHz(hz) {
  if (!(hz > 0) || !Number.isFinite(hz)) return false;
  const log2 = Math.log2(hz);
  return Math.abs(log2 - Math.round(log2)) < 1e-9;
}

function hzToInterval(hz) {
  return -Math.round(Math.log2(hz));
}

const HZ_FIELDS = ["ptp-sync-hz", "ptp-announce-hz", "ptp-delay-request-hz"];

function clearHzErrors() {
  for (const id of HZ_FIELDS) {
    document.getElementById(id).classList.remove("input-error");
    document.getElementById(`${id}-error`).classList.remove("visible");
  }
}

function showHzError(id) {
  document.getElementById(id).classList.add("input-error");
  document.getElementById(`${id}-error`).classList.add("visible");
}

async function loadPtpConfig() {
  const res = await fetch("/api/ptp/config");
  const cfg = await res.json();
  document.getElementById("ptp-domain").value = cfg.domain;
  document.getElementById("ptp-priority1").value = cfg.priority1;
  document.getElementById("ptp-priority2").value = cfg.priority2;
  document.getElementById("ptp-sync-hz").value = intervalToHz(cfg.sync_interval);
  document.getElementById("ptp-announce-hz").value = intervalToHz(cfg.announce_interval);
  document.getElementById("ptp-delay-request-hz").value = intervalToHz(cfg.delay_request_interval);
  document.getElementById("ptp-lock-threshold-ns").value = cfg.lock_threshold_ns;
  document.getElementById("ptp-lock-stable-sec").value = cfg.lock_stable_sec;
  document.getElementById("ptp-offset-alert-threshold-ns").value = cfg.offset_alert_threshold_ns;
}

document.getElementById("btn-save-ptp").addEventListener("click", async () => {
  clearHzErrors();

  const hzValues = {};
  let hasError = false;
  for (const id of HZ_FIELDS) {
    const hz = Number(document.getElementById(id).value);
    if (!isValidHz(hz)) {
      showHzError(id);
      hasError = true;
    } else {
      hzValues[id] = hz;
    }
  }
  if (hasError) return; // config.jsonへの書き込みは行わない

  const payload = {
    domain: Number(document.getElementById("ptp-domain").value),
    priority1: Number(document.getElementById("ptp-priority1").value),
    priority2: Number(document.getElementById("ptp-priority2").value),
    sync_interval: hzToInterval(hzValues["ptp-sync-hz"]),
    announce_interval: hzToInterval(hzValues["ptp-announce-hz"]),
    delay_request_interval: hzToInterval(hzValues["ptp-delay-request-hz"]),
    lock_threshold_ns: Number(document.getElementById("ptp-lock-threshold-ns").value),
    lock_stable_sec: Number(document.getElementById("ptp-lock-stable-sec").value),
    offset_alert_threshold_ns: Number(document.getElementById("ptp-offset-alert-threshold-ns").value),
  };
  await fetch("/api/ptp/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  alert("PTP設定を保存しました。PTPコンテナを再起動します。");
});

document.getElementById("btn-clear-ptp-log").addEventListener("click", async () => {
  if (!confirm("PTPログ(計測ログ・イベントログ)を全て消去します。よろしいですか？")) return;
  await fetch("/api/ptp/log", { method: "DELETE" });
  alert("ログを消去しました。");
});

// --- システム設定タブ ---

// NIC選択プルダウン(NIC割り当て3つ)。要件定義書ver1.01 3.4.4:
// ホストのNIC IDを自動取得してプルダウンで選択させる。
const NIC_SELECT_IDS = ["sys-nic-amber", "sys-nic-blue", "sys-nic-control"];

// IPアドレス設定の3ペイン。NIC役割名(config.jsonのキー)と対応させる。
const IP_ROLES = ["media_nic_amber", "media_nic_blue", "control_nic"];

function setSelectValueSafe(select, value) {
  if (!value) return;
  const exists = Array.from(select.options).some((o) => o.value === value);
  if (!exists) {
    // configの値が現在検出されているNIC一覧に無い場合でも選択肢として残す
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = `${value} (未検出)`;
    select.appendChild(opt);
  }
  select.value = value;
}

async function loadAvailableNics() {
  const res = await fetch("/api/system/nics");
  const data = await res.json();

  for (const id of NIC_SELECT_IDS) {
    const select = document.getElementById(id);
    const previous = select.value;
    select.innerHTML = "";

    if (id === "sys-nic-blue") {
      const emptyOpt = document.createElement("option");
      emptyOpt.value = "";
      emptyOpt.textContent = "(未使用)";
      select.appendChild(emptyOpt);
    }

    for (const name of data.nics) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }

    if (Array.from(select.options).some((o) => o.value === previous)) {
      select.value = previous;
    }
  }
}

async function loadSystemConfig() {
  const res = await fetch("/api/system/config");
  const cfg = await res.json();
  setSelectValueSafe(document.getElementById("sys-nic-amber"), cfg.nics.media_nic_amber);
  setSelectValueSafe(document.getElementById("sys-nic-blue"), cfg.nics.media_nic_blue);
  setSelectValueSafe(document.getElementById("sys-nic-control"), cfg.nics.control_nic);

  // IPアドレス設定の3ペインに、現在割り当てられているNICと現在のIP設定値を反映する
  // (要件定義書ver1.01: NIC①②③ごとのペインに現在の設定値を表示して編集できるようにする)
  for (const role of IP_ROLES) {
    const iface = cfg.nics[role];
    const current = (cfg.ip_settings && cfg.ip_settings[role]) || {};
    const pane = document.getElementById(`ip-pane-${role}`);
    const ifaceLabel = document.getElementById(`ip-iface-${role}`);
    const dhcpEl = document.getElementById(`ip-dhcp-${role}`);
    const addressEl = document.getElementById(`ip-address-${role}`);
    const gatewayEl = document.getElementById(`ip-gateway-${role}`);

    pane.dataset.interface = iface || "";

    if (!iface) {
      ifaceLabel.textContent = "(未割り当て)";
      pane.classList.add("disabled");
      dhcpEl.disabled = true;
      addressEl.disabled = true;
      gatewayEl.disabled = true;
      dhcpEl.checked = false;
      addressEl.value = "";
      gatewayEl.value = "";
      continue;
    }

    ifaceLabel.textContent = `(${iface})`;
    pane.classList.remove("disabled");
    dhcpEl.disabled = false;
    addressEl.disabled = false;
    gatewayEl.disabled = false;
    dhcpEl.checked = false;
    addressEl.value = current.address || "";
    gatewayEl.value = current.gateway || "";
  }
}

document.getElementById("btn-save-nics").addEventListener("click", async () => {
  if (!confirm("本システムを再起動します。よろしいですか？")) return;
  const payload = {
    nics: {
      media_nic_amber: document.getElementById("sys-nic-amber").value,
      media_nic_blue: document.getElementById("sys-nic-blue").value,
      control_nic: document.getElementById("sys-nic-control").value,
    },
  };
  await fetch("/api/system/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  alert("本システムを再起動します。");
});

document.getElementById("btn-save-ip").addEventListener("click", async () => {
  if (!confirm("サーバーOSを再起動します。よろしいですか？")) return;

  const ipAddresses = [];
  for (const role of IP_ROLES) {
    const pane = document.getElementById(`ip-pane-${role}`);
    const iface = pane.dataset.interface;
    if (!iface) continue; // NIC未割り当てのペインはスキップ(要件: NIC②はオプション)

    ipAddresses.push({
      interface: iface,
      dhcp: document.getElementById(`ip-dhcp-${role}`).checked,
      address: document.getElementById(`ip-address-${role}`).value || null,
      gateway: document.getElementById(`ip-gateway-${role}`).value || null,
    });
  }

  if (ipAddresses.length === 0) {
    alert("設定対象のNICが割り当てられていません。");
    return;
  }

  await fetch("/api/system/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ip_addresses: ipAddresses }),
  });
  alert("サーバーOSを再起動します。");
});

document.getElementById("btn-export-config").addEventListener("click", () => {
  window.location.href = "/api/config/export";
});

document.getElementById("btn-import-config").addEventListener("click", () => {
  document.getElementById("import-file").click();
});

document.getElementById("import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  await fetch("/api/config/import", { method: "POST", body: formData });
  alert("設定をインポートしました。PTPコンテナを再起動します。");
  loadPtpConfig();
});

document.getElementById("btn-restart").addEventListener("click", async () => {
  if (!confirm("本システムを再起動します。よろしいですか？")) return;
  await fetch("/api/system/restart", { method: "POST" });
  alert("本システムを再起動します。");
});

document.getElementById("btn-reboot").addEventListener("click", async () => {
  if (!confirm("サーバーOSを再起動します。よろしいですか？")) return;
  await fetch("/api/system/reboot", { method: "POST" });
  alert("サーバーOSを再起動します。");
});

document.getElementById("btn-shutdown").addEventListener("click", async () => {
  if (!confirm("サーバーをシャットダウンします。よろしいですか？")) return;
  await fetch("/api/system/shutdown", { method: "POST" });
  alert("サーバーをシャットダウンします。");
});

loadPtpConfig();
loadAvailableNics().then(loadSystemConfig);
