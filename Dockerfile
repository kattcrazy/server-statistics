# Build from python (plan Tweak 1: Glances venv can't safely add our deps)
FROM python:3.12-slim

# Install system deps: util-linux for dmesg
RUN apt-get update && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

# Install Glances + web server (FastAPI) + our deps
COPY scripts/requirements.txt /opt/monitoring/scripts/requirements.txt
RUN pip install --no-cache-dir glances fastapi uvicorn \
    && pip install --no-cache-dir -r /opt/monitoring/scripts/requirements.txt

COPY scripts/ /opt/monitoring/scripts/
COPY entrypoint.sh /opt/monitoring/entrypoint.sh
WORKDIR /opt/monitoring/scripts
RUN chmod +x /opt/monitoring/entrypoint.sh

ENTRYPOINT ["/opt/monitoring/entrypoint.sh"]
