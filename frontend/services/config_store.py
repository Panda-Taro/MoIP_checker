"""config/config.json の原子的読み書き(要件定義書 7.5.1)。

routers/ptp.py・routers/system.py・routers/config.py から共通利用する。
"""

import json
import os
import threading
from string import Template
from typing import Any

CONFIG_PATH = "/app/config/config.json"
PTP4L_TEMPLATE_PATH = "/app/config/ptp4l.conf.template"
PTP4L_CONF_PATH = "/app/config/ptp4l.conf"

_lock = threading.Lock()


def load_config() -> dict[str, Any]:
    with _lock:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


def save_config(data: dict[str, Any]) -> None:
    """一時ファイルに書いてから os.replace でアトミックに置き換える"""
    with _lock:
        tmp_path = CONFIG_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_PATH)


def update_section(section: str, patch: dict[str, Any]) -> dict[str, Any]:
    """config.json内の1セクション(ptp/system/node)を部分更新して保存する"""
    config = load_config()
    config.setdefault(section, {}).update(patch)
    save_config(config)
    return config


def render_ptp4l_conf() -> str:
    """config.jsonのptpセクションからconfig/ptp4l.confを生成する(要件定義書7.2.3)

    使用NICは要件定義書3.2.6により常にNIC①(Amber)固定。
    """
    config = load_config()
    ptp_cfg = config["ptp"]
    interface = config["system"]["media_nic_amber"]

    with open(PTP4L_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = Template(f.read())

    rendered = template.substitute(
        domain=ptp_cfg["domain"],
        priority1=ptp_cfg["priority1"],
        priority2=ptp_cfg["priority2"],
        sync_interval=ptp_cfg["sync_interval"],
        announce_interval=ptp_cfg["announce_interval"],
        delay_request_interval=ptp_cfg["delay_request_interval"],
        interface=interface,
    )

    tmp_path = PTP4L_CONF_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    os.replace(tmp_path, PTP4L_CONF_PATH)
    return rendered
