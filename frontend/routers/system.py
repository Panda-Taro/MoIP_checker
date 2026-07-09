"""システム設定・再起動・シャットダウンAPI(要件定義書 6.2④)

+ ①-2ペイン(CPU/メモリ/NIC/エラーログ)向けの GET /api/system/status・/api/system/log
  (要件定義書のAPI一覧には無いが、実装計画5章の判断で追加)
"""

import ctypes
import ctypes.util
import ipaddress
import json
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
CLOUD_INIT_DISABLE_PATH = "/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg"

# glibcのreboot(3)ライブラリ関数(sys/reboot.h)に渡すhowto値。
# カーネルのreboot(2)システムコール本体は magic1/magic2/cmd/arg の4引数だが、
# glibcのreboot()ラッパーは howto の1引数のみを取り、magic番号は内部で自動付加する。
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


def _default_gateways() -> dict[str, str]:
    """`ip -j route show default`でインターフェース毎のデフォルトゲートウェイを取得する"""
    try:
        result = subprocess.run(
            ["ip", "-j", "route", "show", "default"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        routes = json.loads(result.stdout)
        return {r["dev"]: r["gateway"] for r in routes if r.get("dev") and r.get("gateway")}
    except Exception:
        logger.exception("failed to read default gateways via 'ip route show default'")
        return {}


def _current_ip_settings(nic_roles: dict[str, str]) -> dict[str, dict]:
    """NIC役割(media_nic_amber等)ごとに現在のIPアドレス(CIDR)・デフォルトゲートウェイを取得する。

    要件定義書ver1.01: WebGUIのIPアドレス設定に現在の設定値を表示するために使う。
    """
    addrs = psutil.net_if_addrs()
    gateways = _default_gateways()
    result: dict[str, dict] = {}

    for role, iface in nic_roles.items():
        if not iface:
            result[role] = {"interface": iface, "address": None, "gateway": None}
            continue

        ipv4 = next((a for a in addrs.get(iface, []) if a.family.name == "AF_INET"), None)
        address = None
        if ipv4 is not None and ipv4.netmask:
            try:
                prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{ipv4.netmask}").prefixlen
                address = f"{ipv4.address}/{prefixlen}"
            except ValueError:
                address = ipv4.address

        result[role] = {"interface": iface, "address": address, "gateway": gateways.get(iface)}

    return result


@router.get("/config")
async def get_system_config():
    """NIC設定①②③・IPアドレスを取得(要件定義書6.2④)"""
    system_cfg = config_store.load_config()["system"]
    return {"nics": system_cfg, "ip_settings": _current_ip_settings(system_cfg)}


def _disable_cloud_init_networking() -> None:
    """cloud-initによるネットワーク設定の自動生成を無効化する。

    本装置は検証専用サーバーとして複数台に展開される想定であり、cloud-initが
    起動毎にnetplan設定(50-cloud-init.yaml等)を再生成し続けると、本アプリが書く
    設定と競合し続ける(下記_neutralize_conflicting_netplan_filesだけでは、再生成
    される度に競合が復活する)。そのため恒久的にcloud-init側のネットワーク管理を
    停止する。
    """
    os.makedirs(os.path.dirname(CLOUD_INIT_DISABLE_PATH), exist_ok=True)
    with open(CLOUD_INIT_DISABLE_PATH, "w", encoding="utf-8") as f:
        f.write("network: {config: disabled}\n")
    logger.info("disabled cloud-init network config management (%s)", CLOUD_INIT_DISABLE_PATH)


def _neutralize_conflicting_netplan_files(interfaces: list[str]) -> None:
    """他のnetplanファイル(cloud-init生成分等)に同じインターフェースの定義が残っていると、
    netplanはaddresses等のリスト型プロパティをマージしてしまい、旧IPが残り続けて
    我々の設定が反映されない。対象インターフェースの定義を他ファイルから削除し、
    NETPLAN_PATHを唯一の設定源にする。
    """
    netplan_dir = os.path.dirname(NETPLAN_PATH)
    for name in sorted(os.listdir(netplan_dir)):
        path = os.path.join(netplan_dir, name)
        if os.path.abspath(path) == os.path.abspath(NETPLAN_PATH) or not name.endswith((".yaml", ".yml")):
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            logger.exception("failed to read netplan file %s", path)
            continue

        ethernets = (data.get("network") or {}).get("ethernets") or {}
        removed = [iface for iface in interfaces if iface in ethernets]
        if not removed:
            continue
        for iface in removed:
            del ethernets[iface]

        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False)
            os.chmod(path, 0o600)
            logger.info("removed conflicting netplan definition for %s from %s", removed, path)
        except Exception:
            logger.exception("failed to rewrite netplan file %s", path)


def _write_netplan(ip_configs: list[NicIpConfig]) -> None:
    """netplan設定を書き換える(実装計画5.1: config.jsonにIP欄が無いためnetplanを直接編集)

    cloud-init等、他のnetplanファイルとの競合(同一インターフェースのaddressesが
    マージされ旧IPが残り続ける問題)を避けるため、cloud-initのネットワーク管理を
    無効化し、他ファイルの同インターフェース定義を削除してから自身のファイルを書き込む。
    """
    _disable_cloud_init_networking()

    interfaces = [cfg.interface for cfg in ip_configs]
    _neutralize_conflicting_netplan_files(interfaces)

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
    rendered = yaml.safe_dump(network, default_flow_style=False)
    with open(NETPLAN_PATH, "w", encoding="utf-8") as f:
        f.write(rendered)
    # netplanは他ユーザーが読み取り可能なパーミッションの設定ファイルを警告・スキップする
    # ことがある(機密情報漏洩防止のため)。root専用(600)に固定して確実に適用させる。
    os.chmod(NETPLAN_PATH, 0o600)
    # netplan自体の適用はホストOS起動時に行われ、コンテナ内からは観測できないため、
    # 書き込んだ内容だけはここでログに残す(docker logsで確認できるようにする)。
    logger.info("wrote netplan config to %s (mode 600):\n%s", NETPLAN_PATH, rendered)


def _restart_ptp_container_sync() -> None:
    try:
        client = docker.from_env()
        client.containers.get("moip-ptp").restart(timeout=5)
    except Exception:
        logger.exception("failed to restart moip-ptp container")


def _do_restart_system() -> None:
    """本システム(frontend+ptpコンテナ)を再起動する(実装計画2.2)"""
    logger.info("system restart: scheduled task started, sleeping 1s")
    time.sleep(1)
    logger.info("system restart: restarting moip-ptp container")
    _restart_ptp_container_sync()
    logger.info("system restart: exiting frontend process now (restart: unless-stopped が再起動する)")
    os._exit(0)  # restart: unless-stopped によりComposeが自動的にfrontendを再起動する


def _reboot_syscall(howto: int) -> None:
    """glibcのreboot(3)を呼び出す(pid:host + privileged:true が前提)。

    `reboot`/`shutdown`コマンドは多くのディストリビューションでsystemctl経由の
    シンボリックリンクであり、systemdとのD-Bus通信(/run/systemd等)を必要とする。
    本コンテナはホストの/runを共有していないためコマンド実行では失敗する。
    pid: host によりPID名前空間がホストと同一になっているため、カーネルの
    reboot(2)を直接呼べば(CAP_SYS_BOOTはprivileged:trueで付与済み)確実にホスト
    本体へ効く。glibcのreboot()ラッパーはhowto1引数のみを取る(magic番号は内部で
    自動付加されるため渡さない。4引数で呼ぶとEINVALになる)。
    """
    os.sync()
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.reboot.argtypes = [ctypes.c_int]
    libc.reboot.restype = ctypes.c_int
    result = libc.reboot(howto)
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
                # ままptp4lが起動してしまう。ここで例外が起きても本システム再起動
                # 自体は必ず実行する(片方の失敗が他方をブロックしないようにする)。
                try:
                    config_store.render_ptp4l_conf()
                except Exception:
                    logger.exception("failed to regenerate ptp4l.conf after NIC assignment change")
            logger.info("scheduling system restart due to NIC assignment change: %s", updates)
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
