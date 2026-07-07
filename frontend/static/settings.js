// MoIP_checker 設定変更(WebGUI②)のクライアント側ロジック

// --- タブ切り替え ---
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
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
async function loadSystemConfig() {
  const res = await fetch("/api/system/config");
  const cfg = await res.json();
  document.getElementById("sys-nic-amber").value = cfg.nics.media_nic_amber;
  document.getElementById("sys-nic-blue").value = cfg.nics.media_nic_blue;
  document.getElementById("sys-nic-control").value = cfg.nics.control_nic;
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
  const payload = {
    ip_addresses: [
      {
        interface: document.getElementById("sys-ip-interface").value,
        dhcp: document.getElementById("sys-ip-dhcp").checked,
        address: document.getElementById("sys-ip-address").value || null,
        gateway: document.getElementById("sys-ip-gateway").value || null,
      },
    ],
  };
  await fetch("/api/system/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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
loadSystemConfig();
