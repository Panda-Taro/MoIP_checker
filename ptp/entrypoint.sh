#!/bin/sh
set -e

CONF=/config/ptp4l.conf
LOG_DIR=/var/log/ptp
LOG=$LOG_DIR/ptp4l.log

mkdir -p "$LOG_DIR"

# config/ptp4l.conf がまだ生成されていない場合(初回起動、WebGUIから未保存)は、
# ビルド時に同梱したデフォルトconfを待避コピーする(実装計画 7.1参照)。
if [ ! -f "$CONF" ]; then
    echo "[entrypoint] $CONF not found. Copying built-in default config."
    cp /opt/ptp4l.conf.default "$CONF"
fi

echo "[entrypoint] starting ptp4l with $CONF"
exec ptp4l -f "$CONF" -m -q >> "$LOG" 2>&1
