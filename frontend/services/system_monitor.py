"""CPU・メモリ使用率・NIC状態の取得(要件定義書 3.4.3 ①-2システム領域)。

要件定義書のAPI一覧(6.2)には①-2ペイン用のエンドポイントが明示されていないため、
実装計画5章の判断に基づき GET /api/system/status / GET /api/system/log として追加する。
"""

import collections
import json
import logging
import subprocess
import time

import psutil

logger = logging.getLogger("moip.system_monitor")

_MAX_LOG_ENTRIES = 500  # WebGUIには最新100件のみ表示するが、内部バッファは少し多めに保持
_log_buffer: collections.deque = collections.deque(maxlen=_MAX_LOG_ENTRIES)

_prev_counters: dict[str, tuple[float, int]] = {}  # name -> (timestamp, total_bytes)


class MemoryLogHandler(logging.Handler):
    """アプリ全体のログをメモリ上に保持し、WebGUIのエラーログ表示に使う(要件定義書3.3, 3.4.3)"""

    def emit(self, record: logging.LogRecord) -> None:
        _log_buffer.append(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )


def install_log_capture() -> None:
    handler = MemoryLogHandler()
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)


def get_recent_logs(limit: int = 100) -> list[dict]:
    return list(_log_buffer)[-limit:]


def get_cpu_mem() -> dict:
    return {
        "cpu_pct": psutil.cpu_percent(interval=0.1),
        "mem_pct": psutil.virtual_memory().percent,
    }


def get_nic_status(nic_names: list[str]) -> list[dict]:
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    now = time.monotonic()
    result = []

    for name in nic_names:
        if not name:
            continue
        if_stats = stats.get(name)
        link_up = bool(if_stats.isup) if if_stats else False

        rate_mbps = 0.0
        if_counters = counters.get(name)
        if if_counters is not None:
            total_bytes = if_counters.bytes_recv + if_counters.bytes_sent
            prev = _prev_counters.get(name)
            if prev is not None:
                prev_ts, prev_bytes = prev
                elapsed = now - prev_ts
                if elapsed > 0:
                    rate_mbps = ((total_bytes - prev_bytes) * 8 / elapsed) / 1_000_000
            _prev_counters[name] = (now, total_bytes)

        result.append({"name": name, "link_up": link_up, "rate_mbps": round(max(rate_mbps, 0.0), 2)})

    return result


# ループバックとDocker自身が生成する仮想インターフェースはプルダウンの選択肢として
# 意味を持たない(素人ユーザーが物理NICと誤認する恐れがある)ため除外する。
_EXCLUDED_PREFIXES = ("lo", "docker", "br-", "veth")


def list_network_interfaces() -> list[str]:
    """ip link show を直接実行してホストのNIC一覧を取得する(要件定義書ver1.01 3.4.4)。

    psutilではなくサブプロセスで`ip`コマンドを直接叩くのは、サーバー環境(ライブラリの
    バージョン差異等)に依存せず常に同じ挙動になることを優先するため。
    システム設定タブを開くたびに呼び出し、1回だけの取得にしない(要件どおり)。

    frontendコンテナは network_mode: host で動作しており、ホストのネットワーク
    名前空間を共有しているため、ここで取得できるのはホストの実NIC一覧そのもの
    (ifconfig/ip link showで見えるものと同一)である。
    """
    try:
        result = subprocess.run(
            ["ip", "-j", "link", "show"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        links = json.loads(result.stdout)
        return sorted(
            link["ifname"]
            for link in links
            if not link.get("ifname", "").startswith(_EXCLUDED_PREFIXES)
        )
    except Exception:
        logger.exception("failed to list network interfaces via 'ip link show'")
        return []
