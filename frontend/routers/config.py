"""設定エクスポート・インポートAPI(要件定義書 6.2⑤・8章)

エクスポート/インポートは「システム設定」(NIC割り当て・IPアドレス)の項目を除く
全ての設定を対象とする(要件定義書8章の記載どおり)。
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, File, UploadFile
from fastapi.responses import JSONResponse

from routers.ptp import restart_ptp_container
from services import config_store, ptp_log_reader

logger = logging.getLogger("moip.routers.config")
router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/export")
async def export_config():
    """全設定をJSONファイルでエクスポート(システム設定を除く)"""
    config = config_store.load_config()
    exportable = {k: v for k, v in config.items() if k != "system"}
    return JSONResponse(
        content=exportable,
        headers={"Content-Disposition": "attachment; filename=moip_checker_config.json"},
    )


@router.post("/import")
async def import_config(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """JSONファイルから全設定をインポート(システム設定を除く)"""
    raw = await file.read()
    imported = json.loads(raw)

    current = config_store.load_config()
    for key, value in imported.items():
        if key == "system":
            continue  # システム設定はインポート対象外(要件定義書8章)
        current[key] = value
    config_store.save_config(current)

    config_store.render_ptp4l_conf()
    ptp_log_reader.reload_config()
    background_tasks.add_task(restart_ptp_container)

    return {"status": "imported"}
