"""システム設定・再起動・シャットダウンAPI(要件定義書 6.2④)

+ ①-2ペイン(CPU/メモリ/NIC/エラーログ)向けの GET /api/system/status・/api/system/log
  (要件定義書のAPI一覧には無いが、実装計画5章の判断で追加)
"""

import logging
import os
import subprocess
import time

import docker
import psutil
import yaml
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from services import config_store, system_monitor

logger = logging.getLogger("moip.routers.system")
router = APIRouter(prefix="/api/system", tags=["system"])

NETPLAN_PATH = "/etc/netplan/99-moip-checker.yaml"


class NicAssignment(BaseModel):
    media_nic_amber: str | None = None
    media_nic_blue: str | None = None
    control_nic: str | None = None


class NicIpConfig(BaseModel):
    interface: str
    dhcp: bool = False
    address: str | None = None  # CIDR形式 例: "192.168.1.10/24"
    gateway: str | None = None


class SystemConfigUpdate(BaseModel):
    nics: NicAssignment | None = None
    ip_addresses: list[NicIpConfig] | None = None


def _current_ip_addresses(nic_names: list[str]) -> dict[str, str | None]:
    addrs = psutil.net_if_addrs()
    result: dict[str, str | None] = {}
    for name in nic_names:
        if not name:
            continue
        ipv4 = next((a.address for a in addrs.get(name, []) if a.family.name == "AF_INET"), None)
        result[name] = ipv4
    return result


@router.get("/config")
async def get_system_config():
    """NIC設定①②③・IPアドレスを取得(要件定義書6.2④)"""
    system_cfg = config_store.load_config()["system"]
    nic_names = list(system_cfg.values())
    return {"nics": system_cfg, "current_ip_addresses": _current_ip_addresses(nic_names)}


def _write_netplan(ip_configs: list[NicIpConfig]) -> None:
    """netplan設定を書き換える(実装計画5.1: config.jsonにIP欄が無いためnetplanを直接編集)"""
    ethernets = {}
    for cfg in ip_configs:
        entry: dict = {"dhcp4": cfg.dhcp}
        if not cfg.dhcp:
            if cfg.address:
                entry["addresses"] = [cfg.address]
            if cfg.gateway:
                entry["routes"] = [{"to": "default", "via": cfg.gateway}]
        ethernets[cfg.interface] = entry

    network = {"network": {"version": 2, "ethernets": ethernets}}
    with open(NETPLAN_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(network, f, default_flow_style=False)


def _restart_ptp_container_sync() -> None:
    try:
        client = docker.from_env()
        client.containers.get("moip-ptp").restart(timeout=5)
    except Exception:
        logger.exception("failed to restart moip-ptp container")


def _do_restart_system() -> None:
    """本システム(frontend+ptpコンテナ)を再起動する(実装計画2.2)"""
    time.sleep(1)
    _restart_ptp_container_sync()
    os._exit(0)  # restart: unless-stopped によりComposeが自動的にfrontendを再起動する


def _do_reboot_os() -> None:
    """サーバーOSを再起動する(実装計画2.3: pid:host + privileged前提)"""
    time.sleep(1)
    subprocess.run(["reboot"], check=False)


def _do_shutdown_os() -> None:
    time.sleep(1)
    subprocess.run(["shutdown", "-h", "now"], check=False)


@router.post("/config")
async def update_system_config(patch: SystemConfigUpdate, background_tasks: BackgroundTasks):
    """システム設定値を変更・保存(要件定義書6.2④・8章)

    NIC割り当て変更 → 本システム再起動、IPアドレス変更 → サーバーOS再起動。
    """
    actions = []

    if patch.nics is not None:
        updates = {k: v for k, v in patch.nics.model_dump().items() if v is not None}
        if updates:
            config_store.update_section("system", updates)
            background_tasks.add_task(_do_restart_system)
            actions.append("system_restart")

    if patch.ip_addresses is not None and len(patch.ip_addresses) > 0:
        _write_netplan(patch.ip_addresses)
        background_tasks.add_task(_do_reboot_os)
        actions.append("os_reboot")

    return {"status": "ok", "actions": actions}


@router.post("/restart")
async def restart_system(background_tasks: BackgroundTasks):
    """本システム再起動(要件定義書6.2④)"""
    background_tasks.add_task(_do_restart_system)
    return {"status": "restarting"}


@router.post("/reboot")
async def reboot_server(background_tasks: BackgroundTasks):
    """サーバーOS再起動(要件定義書6.2④)"""
    background_tasks.add_task(_do_reboot_os)
    return {"status": "rebooting"}


@router.post("/shutdown")
async def shutdown_server(background_tasks: BackgroundTasks):
    """サーバーシャットダウン(要件定義書6.2④)"""
    background_tasks.add_task(_do_shutdown_os)
    return {"status": "shutting_down"}


@router.get("/status")
async def get_system_status():
    """CPU/メモリ使用率・NIC状態(要件定義書3.4.3 ①-2ペイン向け、実装計画5章で追加)"""
    system_cfg = config_store.load_config()["system"]
    nic_names = list(system_cfg.values())
    cpu_mem = system_monitor.get_cpu_mem()
    nics = system_monitor.get_nic_status(nic_names)
    return {**cpu_mem, "nics": nics, "error_log_count": len(system_monitor.get_recent_logs())}


@router.get("/log")
async def get_system_log(limit: int = 100):
    """システムエラーログ最新N件(要件定義書3.4.3、実装計画5章で追加)"""
    return {"logs": system_monitor.get_recent_logs(limit)}


@router.get("/nics")
async def get_available_nics():
    """ホストのNIC一覧を毎回取得する(要件定義書ver1.01 3.4.4: ip link show相当)

    システム設定タブのNIC選択プルダウン用。起動時の1回きりの取得ではなく、
    呼び出しごとに`ip link show`を実行して最新の状態を返す。
    """
    return {"nics": system_monitor.list_network_interfaces()}
