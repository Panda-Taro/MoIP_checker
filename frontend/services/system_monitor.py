"""CPU・メモリ使用率・NIC状態の取得(要件定義書 3.4.3 ①-2システム領域)。

要件定義書のAPI一覧(6.2)には①-2ペイン用のエンドポイントが明示されていないため、
実装計画5章の判断に基づき GET /api/system/status / GET /api/system/log として追加する。
"""

import collections
import logging
import time

import psutil

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
