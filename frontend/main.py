"""MoIP_checker frontend (コンテナ①) FastAPIエントリーポイント"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models.ptp_log import init_db
from routers import config as config_router
from routers import ptp as ptp_router
from routers import system as system_router
from services import ptp_log_reader, system_monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("moip.main")

templates = Jinja2Templates(directory="templates")

_ptp_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    system_monitor.install_log_capture()

    global _ptp_task
    _ptp_task = asyncio.create_task(ptp_log_reader.run())
    logger.info("ptp_log_reader task started")

    yield

    if _ptp_task is not None:
        _ptp_task.cancel()
        try:
            await _ptp_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="MoIP_checker", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(ptp_router.router)
app.include_router(ptp_router.external_router)
app.include_router(system_router.router)
app.include_router(config_router.router)


@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/settings")
async def settings(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})
