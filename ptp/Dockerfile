FROM ubuntu:24.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends linuxptp iproute2 && \
    rm -rf /var/lib/apt/lists/*

COPY ptp4l.conf.template /opt/ptp4l.conf.default
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# network_mode: host で起動する前提(docker-compose.yml)。PTPのマルチキャスト・
# ハードウェア/ソフトウェアタイムスタンプの制約のため、通常のDockerブリッジは使用しない。
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
