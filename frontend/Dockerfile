FROM python:3.12-slim

# reboot/shutdown (util-linux) と ip コマンド(NIC状態取得)が必要
RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux iproute2 iputils-ping netplan.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# network_mode: host で起動するためEXPOSE/ポートマッピングは使わず、
# WEBGUI_PORT環境変数(docker-compose.yml)でホスト上に直接listenするポートを指定する。
# シェル形式+execでPID1をuvicorn自身にし、シグナルハンドリングを正しく機能させる。
CMD exec uvicorn main:app --host 0.0.0.0 --port ${WEBGUI_PORT:-80} --workers 1
