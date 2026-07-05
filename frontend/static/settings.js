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
async function loadPtpConfig() {
  const res = await fetch("/api/ptp/config");
  const cfg = await res.json();
  document.getElementById("ptp-domain").value = cfg.domain;
  document.getElementById("ptp-priority1").value = cfg.priority1;
  document.getElementById("ptp-priority2").value = cfg.priority2;
  document.getElementById("ptp-sync-interval").value = cfg.sync_interval;
  document.getElementById("ptp-announce-interval").value = cfg.announce_interval;
  document.getElementById("ptp-delay-request-interval").value = cfg.delay_request_interval;
  document.getElementById("ptp-lock-threshold-ns").value = cfg.lock_threshold_ns;
  document.getElementById("ptp-lock-stable-sec").value = cfg.lock_stable_sec;
  document.getElementById("ptp-offset-alert-threshold-ns").value = cfg.offset_alert_threshold_ns;
}

document.getElementById("btn-save-ptp").addEventListener("click", async () => {
  const payload = {
    domain: Number(document.getElementById("ptp-domain").value),
    priority1: Number(document.getElementById("ptp-priority1").value),
    priority2: Number(document.getElementById("ptp-priority2").value),
    sync_interval: Number(document.getElementById("ptp-sync-interval").value),
    announce_interval: Number(document.getElementById("ptp-announce-interval").value),
    delay_request_interval: Number(document.getElementById("ptp-delay-request-interval").value),
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
