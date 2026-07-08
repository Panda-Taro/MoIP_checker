"""システム設定・再起動・シャットダウンAPI(要件定義書 6.2④)

+ ①-2ペイン(CPU/メモリ/NIC/エラーログ)向けの GET /api/system/status・/api/system/log
  (要件定義書のAPI一覧には無いが、実装計画5章の判断で追加)
"""

import ctypes
import ctypes.util
import logging
import os
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

# reboot(2)システムコールの定数(linux/reboot.h)
_LINUX_REBOOT_MAGIC1 = 0xFEE1DEAD
_LINUX_REBOOT_MAGIC2 = 672274793
_LINUX_REBOOT_CMD_RESTART = 0x01234567
_LINUX_REBOOT_CMD_POWER_OFF = 0x4321FEDC


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


def _reboot_syscall(cmd: int) -> None:
    """reboot(2)を直接呼び出す(pid:host + privileged:true が前提)。

    `reboot`/`shutdown`コマンドは多くのディストリビューションでsystemctl経由の
    シンボリックリンクであり、systemdとのD-Bus通信(/run/systemd等)を必要とする。
    本コンテナはホストの/runを共有していないためコマンド実行では失敗する。
    pid: host によりPID名前空間がホストと同一になっているため、カーネルの
    reboot(2)を直接呼べば(CAP_SYS_BOOTはprivileged:trueで付与済み)確実にホスト
    本体へ効く。
    """
    os.sync()
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    result = libc.reboot(_LINUX_REBOOT_MAGIC1, _LINUX_REBOOT_MAGIC2, cmd, 0)
    if result != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))


def _do_reboot_os() -> None:
    """サーバーOSを再起動する(実装計画2.3: pid:host + privileged前提)"""
    time.sleep(1)
    try:
        _reboot_syscall(_LINUX_REBOOT_CMD_RESTART)
    except Exception:
        logger.exception("failed to reboot host OS")


def _do_shutdown_os() -> None:
    time.sleep(1)
    try:
        _reboot_syscall(_LINUX_REBOOT_CMD_POWER_OFF)
    except Exception:
        logger.exception("failed to power off host OS")


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
            if "media_nic_amber" in updates:
                # PTPが使うNIC(要件定義書3.2.6: Amberのみ)が変わった場合は、
                # ptp4l.confを再生成してから再起動しないと古いインターフェース名の
                # ままptp4lが起動してしまう。
                config_store.render_ptp4l_conf()
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
