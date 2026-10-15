FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CODEX_CLI_BINARY=/usr/local/bin/codex \
    CODEX_CLI_HOME=/codex-home \
    CODEX_CLI_SHA256_FILE=/opt/codex-reserve/cli.sha256 \
    CODEX_CONNECTOR_BIND=0.0.0.0 \
    CODEX_CONNECTOR_PORT=18999

WORKDIR /opt/codex-reserve

COPY install_cli.py /tmp/install_cli.py
RUN python /tmp/install_cli.py \
    && rm -f /tmp/install_cli.py \
    && python -c "from pathlib import Path; Path('/codex-home').mkdir(); Path('/opt/codex-reserve').mkdir(exist_ok=True)" \
    && useradd --uid 10001 --user-group --home-dir /codex-home --no-create-home --shell /usr/sbin/nologin codex-reserve \
    && chown 10001:10001 /codex-home \
    && chmod 0555 /usr/local/bin/codex \
    && chmod 0444 /opt/codex-reserve/cli.sha256

COPY runner.py server.py egress.py /opt/codex-reserve/
RUN chmod 0555 /opt/codex-reserve/runner.py /opt/codex-reserve/server.py /opt/codex-reserve/egress.py \
    && chmod 0555 /opt/codex-reserve \
    && find /opt/codex-reserve -type d -exec chmod 0555 {} + \
    && chmod 0444 /opt/codex-reserve/cli.sha256

USER 10001:10001
ENTRYPOINT ["python", "/opt/codex-reserve/server.py"]
