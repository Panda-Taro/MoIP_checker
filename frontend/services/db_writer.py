"""SQLiteへの書き込みを1本の専用スレッドに集約する(実装計画 4章)。

非同期タスク(ptp_log_reader)からのenqueueも、DELETE /api/ptp/log からのクリア要求も
すべて同じキューを経由するため、書き込みが競合することはない。
読み取り(GET /api/ptp/log)はWALモードのためリクエストハンドラから直接行ってよい。
"""

import json
import logging
import queue
import threading
from datetime import datetime

from models.ptp_log import PtpEventLog, PtpMeasurementLog, SessionLocal

logger = logging.getLogger("moip.db_writer")

_write_queue: "queue.Queue" = queue.Queue()
_thread: threading.Thread | None = None


def _process(job: dict) -> None:
    kind = job["kind"]
    session = SessionLocal()
    try:
        if kind == "measurement":
            session.add(PtpMeasurementLog(**job["payload"]))
            session.commit()
        elif kind == "event":
            session.add(PtpEventLog(**job["payload"]))
            session.commit()
        elif kind == "clear":
            session.query(PtpMeasurementLog).delete()
            session.query(PtpEventLog).delete()
            session.commit()
    except Exception:
        session.rollback()
        logger.exception("db_writer: failed to process job kind=%s", kind)
    finally:
        session.close()
        if job.get("done_event") is not None:
            job["done_event"].set()


def _writer_loop() -> None:
    while True:
        job = _write_queue.get()
        if job is None:
            break
        _process(job)


def start() -> None:
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_writer_loop, daemon=True, name="db-writer")
        _thread.start()


def stop() -> None:
    _write_queue.put_nowait(None)


def enqueue_measurement(
    lock_status: bool,
    gm_id: str,
    source_id: str,
    offset_avg_ns: int,
    offset_max_ns: int,
    offset_min_ns: int,
) -> None:
    _write_queue.put_nowait(
        {
            "kind": "measurement",
            "payload": {
                "recorded_at": datetime.now().isoformat(),
                "lock_status": 1 if lock_status else 0,
                "gm_id": gm_id,
                "source_id": source_id,
                "offset_avg_ns": offset_avg_ns,
                "offset_max_ns": offset_max_ns,
                "offset_min_ns": offset_min_ns,
            },
        }
    )


def enqueue_event(event_type: str, detail: dict) -> None:
    _write_queue.put_nowait(
        {
            "kind": "event",
            "payload": {
                "recorded_at": datetime.now().isoformat(),
                "event_type": event_type,
                "detail": json.dumps(detail, ensure_ascii=False),
            },
        }
    )


def clear_logs(timeout: float = 5.0) -> None:
    """計測ログ・イベントログを全消去する。書き込みスレッドでの完了を待つ。"""
    done_event = threading.Event()
    _write_queue.put_nowait({"kind": "clear", "done_event": done_event})
    done_event.wait(timeout=timeout)
