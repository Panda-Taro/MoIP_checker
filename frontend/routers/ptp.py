"""PTP状態・設定・ログAPI(要件定義書 6.2 ①②③)+ 外部API(6.3.2)"""

import asyncio
import json
import logging

import docker
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from models.ptp_log import PtpEventLog, PtpMeasurementLog, SessionLocal
from services import config_store, db_writer, ptp_log_reader

logger = logging.getLogger("moip.routers.ptp")

router = APIRouter(prefix="/api/ptp", tags=["ptp"])
external_router = APIRouter(prefix="/api/external", tags=["external"])

# 要件定義書 7.7/7.8 のSSE・外部APIレスポンスに含める公開フィールドのみ
_PUBLIC_FIELDS = (
    "lock_status",
    "gm_id",
    "source_id",
    "offset_avg_ns",
    "offset_max_ns",
    "offset_min_ns",
    "offset_current_ns",
    "last_updated",
)


def _to_public_dict(snapshot: dict) -> dict:
    return {k: snapshot[k] for k in _PUBLIC_FIELDS}


class PtpConfigUpdate(BaseModel):
    domain: int | None = None
    priority1: int | None = None
    priority2: int | None = None
    sync_interval: int | None = None
    announce_interval: int | None = None
    delay_request_interval: int | None = None
    lock_threshold_ns: int | None = None
    lock_stable_sec: int | None = None
    offset_alert_threshold_ns: int | None = None


@router.get("/status")
async def get_ptp_status():
    """1回取得(要件定義書6.2①)。内部デバッグ用フィールド(lock_stable_count等)も含む。"""
    return await ptp_log_reader.get_status()


@router.get("/status/stream")
async def stream_ptp_status():
    """SSEでリアルタイム配信、1秒更新(要件定義書6.2①・7.7)"""

    async def event_generator():
        while True:
            snapshot = await ptp_log_reader.get_status()
            yield {"data": json.dumps(_to_public_dict(snapshot))}
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())


@router.get("/config")
async def get_ptp_config():
    """現在のPTP設定値を取得(要件定義書6.2②)"""
    return config_store.load_config()["ptp"]


def restart_ptp_container() -> None:
    """コンテナ②を再起動する(要件定義書7.2.3)。BackgroundTasksから呼ばれる。"""
    ptp_log_reader.set_restarting(True)
    try:
        client = docker.from_env()
        client.containers.get("moip-ptp").restart(timeout=5)
    except Exception:
        logger.exception("failed to restart moip-ptp container")
    finally:
        ptp_log_reader.set_restarting(False)


@router.post("/config")
async def update_ptp_config(patch: PtpConfigUpdate, background_tasks: BackgroundTasks):
    """PTP設定値を変更・保存し、ptp4l.confを再生成してコンテナ②を再起動する(要件定義書6.2②)"""
    updates = {k: v for k, v in patch.model_dump().items() if v is not None}
    config = config_store.update_section("ptp", updates)
    config_store.render_ptp4l_conf()
    ptp_log_reader.reload_config()
    background_tasks.add_task(restart_ptp_container)
    return {"status": "ok", "ptp": config["ptp"], "restarting": True}


@router.get("/log")
async def get_ptp_log(limit: int = 100):
    """PTPログ一覧取得。CSVエクスポートはWebGUI側でこのJSONから生成する(要件定義書6.2③)"""
    session = SessionLocal()
    try:
        measurements = (
            session.query(PtpMeasurementLog).order_by(PtpMeasurementLog.id.desc()).limit(limit).all()
        )
        events = session.query(PtpEventLog).order_by(PtpEventLog.id.desc()).limit(limit).all()
        return {
            "measurement_logs": [
                {
                    "id": m.id,
                    "recorded_at": m.recorded_at,
                    "lock_status": m.lock_status,
                    "gm_id": m.gm_id,
                    "source_id": m.source_id,
                    "offset_avg_ns": m.offset_avg_ns,
                    "offset_max_ns": m.offset_max_ns,
                    "offset_min_ns": m.offset_min_ns,
                }
                for m in measurements
            ],
            "event_logs": [
                {"id": e.id, "recorded_at": e.recorded_at, "event_type": e.event_type, "detail": e.detail}
                for e in events
            ],
        }
    finally:
        session.close()


@router.delete("/log")
async def delete_ptp_log():
    """PTPログ消去(要件定義書6.2③)"""
    db_writer.clear_logs()
    return {"status": "cleared"}


@external_router.get("/ptp/status")
async def external_ptp_status():
    """Zabbix等の外部監視ツール向け。認証なし、常に200(要件定義書6.3.2・7.8)"""
    snapshot = await ptp_log_reader.get_status()
    return _to_public_dict(snapshot)
