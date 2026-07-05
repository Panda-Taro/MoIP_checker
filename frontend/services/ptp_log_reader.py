"""logs/ptp4l.log を tail し、パースしてメモリ上の状態を更新するサービス
(要件定義書 7.2.1, 7.6, 7.7)。

FastAPIのlifespanから asyncio.create_task(run()) で起動する単一のバックグラウンドタスク。
1本のasyncioイベントループ上で完結させ、単一Uvicornワーカーの制約に適合させる。
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Optional

from services import config_store, db_writer

logger = logging.getLogger("moip.ptp_log_reader")

LOG_PATH = "/app/logs/ptp4l.log"

# 要件定義書 7.6.3 パースパターン
PATTERN_A = re.compile(r"master offset\s+(-?\d+)\s+s(\d)\s+freq\s+(-?\d+)\s+path delay\s+(\d+)")
PATTERN_B = re.compile(r"selected best master clock\s+([0-9a-f]{6}\.fffe\.[0-9a-f]{6})")
PATTERN_C = re.compile(r"port \d+: (\w+) to (\w+) on")

_lock = asyncio.Lock()

# WebGUI/SSE/外部APIに公開する状態(要件定義書 7.6.4/7.7.2 のJSON形状に準拠)
_state: dict = {
    "lock_status": False,
    "gm_id": "unknown",
    "source_id": "unknown",
    "offset_current_ns": 0,
    "offset_avg_ns": 0,
    "offset_max_ns": 0,
    "offset_min_ns": 0,
    "lock_stable_count": 0,
    "last_updated": datetime.now().isoformat(),
}

# 内部作業用(公開しない)
_second_samples: list[int] = []
_minute_samples: list[int] = []
_sync_state = 0  # 0=UNLOCKED, 1=CALIBRATING, 2=LOCKED (ptp4lの s0/s1/s2)
_last_sync_seen_at: Optional[float] = None
_freq_error_miss_count = 0
_freq_error_active = False
_offset_threshold_breached = False
_restarting = False

# config.jsonから読み込むしきい値のキャッシュ(POST /api/ptp/config 保存時にreload_config()で更新)
_cfg = {
    "lock_threshold_ns": 500,
    "lock_stable_sec": 3,
    "offset_alert_threshold_ns": 500,
    "sync_interval": -7,
}


def reload_config() -> None:
    """config.json の ptp セクションが変更された際に呼ぶ(routers/ptp.py から)"""
    ptp_cfg = config_store.load_config()["ptp"]
    _cfg["lock_threshold_ns"] = ptp_cfg["lock_threshold_ns"]
    _cfg["lock_stable_sec"] = ptp_cfg["lock_stable_sec"]
    _cfg["offset_alert_threshold_ns"] = ptp_cfg["offset_alert_threshold_ns"]
    _cfg["sync_interval"] = ptp_cfg["sync_interval"]


def set_restarting(flag: bool) -> None:
    global _restarting
    _restarting = flag


def _derive_source_id(gm_id: str) -> str:
    """gm_id(clockIdentity)からfffeパディングを除去してMAC風文字列を生成する。

    設計判断(実装計画 3章): ptp4l標準ログにはAnnounce送信元のMACが出力されないため、
    gm_id (例: 001b21.fffe.000001) からEUI-64パディング(fffe)を除去して
    00:1b:21:00:00:01 のようなMAC風文字列を作る。単一ホップ構成では同期元は
    グランドマスターと同一のため実用上妥当な近似となる。
    """
    parts = gm_id.split(".")
    if len(parts) != 3:
        return "unknown"
    combined = parts[0] + parts[2]
    return ":".join(combined[i : i + 2] for i in range(0, len(combined), 2))


def _parse_line(line: str) -> None:
    """1行パースして内部状態を更新する(ロック中で呼ぶこと)"""
    global _sync_state, _last_sync_seen_at

    match_a = PATTERN_A.search(line)
    if match_a:
        offset_ns = int(match_a.group(1))
        _sync_state = int(match_a.group(2))
        _second_samples.append(offset_ns)
        _state["offset_current_ns"] = offset_ns
        _last_sync_seen_at = time.monotonic()
        return

    match_b = PATTERN_B.search(line)
    if match_b:
        new_gm_id = match_b.group(1)
        if new_gm_id != _state["gm_id"] and _state["gm_id"] != "unknown":
            db_writer.enqueue_event(
                "GM_ID_CHANGED",
                {"previous_gm_id": _state["gm_id"], "new_gm_id": new_gm_id},
            )
        _state["gm_id"] = new_gm_id
        _state["source_id"] = _derive_source_id(new_gm_id)
        return

    match_c = PATTERN_C.search(line)
    if match_c:
        # port状態遷移。第1期ではロック判定はPattern Aのs2状態を使うため、ここでは
        # ログとしての意味のみを持つ(将来の拡張余地としてコメントのみ残す)。
        return


async def _tick_second() -> None:
    """1秒毎の集計・ロック判定・イベント検出(要件定義書 3.2.8, 3.2.10)"""
    global _freq_error_miss_count, _freq_error_active, _offset_threshold_breached

    async with _lock:
        samples = _second_samples.copy()
        _second_samples.clear()

        if samples:
            avg = sum(samples) // len(samples)
            _state["offset_avg_ns"] = avg
            _state["offset_max_ns"] = max(samples)
            _state["offset_min_ns"] = min(samples)
            _minute_samples.extend(samples)

        # --- ロック判定(実装計画 3.1: sync_state==2 かつ offset<=閾値 のAND、連続secでロック) ---
        offset_ok = abs(_state["offset_current_ns"]) <= _cfg["lock_threshold_ns"]
        locked_this_tick = (_sync_state == 2) and offset_ok
        if locked_this_tick:
            _state["lock_stable_count"] += 1
        else:
            _state["lock_stable_count"] = 0

        was_locked = _state["lock_status"]
        new_lock_status = _state["lock_stable_count"] >= _cfg["lock_stable_sec"]
        if was_locked and not new_lock_status:
            db_writer.enqueue_event(
                "PTP_LOCK_LOST",
                {"previous_offset_ns": _state["offset_current_ns"], "gm_id": _state["gm_id"]},
            )
        _state["lock_status"] = new_lock_status

        # --- Offset閾値超えイベント(エッジ検出) ---
        breached_now = abs(_state["offset_current_ns"]) > _cfg["offset_alert_threshold_ns"]
        if breached_now and not _offset_threshold_breached:
            db_writer.enqueue_event(
                "OFFSET_THRESHOLD",
                {"offset_ns": _state["offset_current_ns"], "threshold_ns": _cfg["offset_alert_threshold_ns"]},
            )
        _offset_threshold_breached = breached_now

        # --- パケット周波数乱れ(Syncパケットのみ、実装計画 3.1の既知の制約) ---
        expected_interval = 2 ** _cfg["sync_interval"]
        if _last_sync_seen_at is not None:
            elapsed = time.monotonic() - _last_sync_seen_at
            if elapsed > expected_interval + 3:
                _freq_error_miss_count += 1
            else:
                _freq_error_miss_count = 0

        if _freq_error_miss_count >= 3 and not _freq_error_active:
            db_writer.enqueue_event("PACKET_FREQ_ERROR", {"packet_type": "sync"})
            _freq_error_active = True
        elif _freq_error_miss_count == 0:
            _freq_error_active = False

        _state["last_updated"] = datetime.now().isoformat()


async def _tick_minute() -> None:
    """1分毎の計測ログ記録(要件定義書 3.2.9)"""
    async with _lock:
        samples = _minute_samples.copy()
        _minute_samples.clear()
        if samples:
            avg, mx, mn = sum(samples) // len(samples), max(samples), min(samples)
        else:
            avg = mx = mn = _state["offset_current_ns"]

        db_writer.enqueue_measurement(
            lock_status=_state["lock_status"],
            gm_id=_state["gm_id"],
            source_id=_state["source_id"],
            offset_avg_ns=avg,
            offset_max_ns=mx,
            offset_min_ns=mn,
        )


async def get_status() -> dict:
    async with _lock:
        snapshot = dict(_state)
    snapshot["restarting"] = _restarting
    return snapshot


async def _second_tick_loop() -> None:
    while True:
        await asyncio.sleep(1)
        try:
            await _tick_second()
        except Exception:
            logger.exception("ptp_log_reader: second tick failed")


async def _minute_tick_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await _tick_minute()
        except Exception:
            logger.exception("ptp_log_reader: minute tick failed")


async def _tail_loop() -> None:
    # tail -F: ptp4lコンテナ起動待ち・ログローテーションに耐える(実装計画3章)
    proc = await asyncio.create_subprocess_exec(
        "tail", "-F", LOG_PATH,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace")
            async with _lock:
                _parse_line(line)
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def run() -> None:
    reload_config()
    db_writer.start()
    await asyncio.gather(
        _tail_loop(),
        _second_tick_loop(),
        _minute_tick_loop(),
    )
