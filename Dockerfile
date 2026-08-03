FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/nms-nova
COPY requirements.txt requirements-dev.txt ./ 
RUN pip install --no-cache-dir -r requirements.txt

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
