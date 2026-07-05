// MoIP_checker ダッシュボード(WebGUI①)のクライアント側ロジック
// PTP状態はSSEで1秒更新、システム状態(CPU/メモリ/NIC)は5秒ポーリング。

let latestMeasurementLogs = [];
let latestEventLogs = [];
let latestSysLogs = [];

function downloadCsv(filename, rows) {
  if (!rows || rows.length === 0) {
    alert("エクスポートするデータがありません");
    return;
  }
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(headers.map((h) => JSON.stringify(row[h] ?? "")).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function renderTable(containerId, rows, columns) {
  const container = document.getElementById(containerId);
  if (!rows || rows.length === 0) {
    container.innerHTML = "<p>データがありません</p>";
    return;
  }
  let html = "<table><thead><tr>";
  for (const col of columns) html += `<th>${col}</th>`;
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += "<tr>" + columns.map((c) => `<td>${row[c] ?? ""}</td>`).join("") + "</tr>";
  }
  html += "</tbody></table>";
  container.innerHTML = html;
}

function updatePtpPane(data) {
  const lockDot = document.getElementById("ptp-lock-dot");
  const lockText = document.getElementById("ptp-lock-text");
  if (data.lock_status) {
    lockDot.classList.add("locked");
    lockText.textContent = "LOCKED";
  } else {
    lockDot.classList.remove("locked");
    lockText.textContent = "UNLOCKED";
  }
  document.getElementById("ptp-gmid").textContent = data.gm_id;
  document.getElementById("ptp-srcid").textContent = data.source_id;
  document.getElementById("ptp-offset").textContent =
    `${data.offset_avg_ns} / ${data.offset_max_ns} / ${data.offset_min_ns}`;
}

function connectPtpStream() {
  const evtSource = new EventSource("/api/ptp/status/stream");
  evtSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    updatePtpPane(data);
  };
  evtSource.onerror = () => {
    // 再接続はEventSourceが自動で行う(再起動中などで一時的に切れても復帰する)
  };
}

async function fetchPtpLogs() {
  try {
    const res = await fetch("/api/ptp/log?limit=100");
    const data = await res.json();
    latestMeasurementLogs = data.measurement_logs;
    latestEventLogs = data.event_logs;
    renderTable("measurement-log-scroll", latestMeasurementLogs, [
      "recorded_at", "lock_status", "gm_id", "source_id", "offset_avg_ns", "offset_max_ns", "offset_min_ns",
    ]);
    renderTable("event-log-scroll", latestEventLogs, ["recorded_at", "event_type", "detail"]);
  } catch (e) {
    console.error("failed to fetch ptp logs", e);
  }
}

async function fetchSystemStatus() {
  try {
    const res = await fetch("/api/system/status");
    const data = await res.json();
    document.getElementById("sys-cpu").textContent = `${data.cpu_pct.toFixed(1)}%`;
    document.getElementById("sys-mem").textContent = `${data.mem_pct.toFixed(1)}%`;
    document.getElementById("sys-log-count").textContent = data.error_log_count;

    const nicsHtml = data.nics
      .map((n) => `<div class="stat-row"><span>${n.name}</span><span>${n.link_up ? "🟢" : "🔴"} ${n.rate_mbps} Mbps</span></div>`)
      .join("");
    document.getElementById("sys-nics").innerHTML = nicsHtml;
  } catch (e) {
    console.error("failed to fetch system status", e);
  }
}

async function fetchSysLogs() {
  const res = await fetch("/api/system/log?limit=100");
  const data = await res.json();
  latestSysLogs = data.logs;
  renderTable("sys-log-scroll", latestSysLogs, ["timestamp", "level", "logger", "message"]);
}

document.getElementById("btn-export-measurement").addEventListener("click", () => {
  downloadCsv("ptp_measurement_logs.csv", latestMeasurementLogs);
});

document.getElementById("btn-export-event").addEventListener("click", () => {
  downloadCsv("ptp_event_logs.csv", latestEventLogs);
});

document.getElementById("btn-clear-log").addEventListener("click", async () => {
  if (!confirm("PTPログ(計測ログ・イベントログ)を全て消去します。よろしいですか？")) return;
  await fetch("/api/ptp/log", { method: "DELETE" });
  await fetchPtpLogs();
});

document.getElementById("btn-show-syslog").addEventListener("click", async () => {
  const box = document.getElementById("sys-log-scroll");
  const showing = box.style.display !== "none";
  if (showing) {
    box.style.display = "none";
  } else {
    await fetchSysLogs();
    box.style.display = "block";
  }
});

document.getElementById("btn-export-syslog").addEventListener("click", async () => {
  await fetchSysLogs();
  downloadCsv("system_error_logs.csv", latestSysLogs);
});

connectPtpStream();
fetchPtpLogs();
fetchSystemStatus();
setInterval(fetchPtpLogs, 10000);
setInterval(fetchSystemStatus, 5000);
