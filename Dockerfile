FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/nms-nova
COPY requirements.txt requirements-dev.txt ./ 
ARG INSTALL_SNMP=0
RUN if [ "$INSTALL_SNMP" = "1" ]; then pip install --no-cache-dir -r requirements.txt "pysnmp>=1.5,<2"; else pip install --no-cache-dir -r requirements.txt; fi

COPY main.py ./main.py
COPY state ./state
COPY probes ./probes
COPY scripts ./scripts
COPY static ./static
COPY api ./api
COPY targets.yaml.example ./targets.yaml.example

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /opt/nms-nova
USER appuser

EXPOSE 8000
CMD ["python", "main.py"]
