FROM python:3.12-slim

# reboot/shutdown (util-linux) と ip コマンド(NIC状態取得)が必要
RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux iproute2 iputils-ping netplan.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
