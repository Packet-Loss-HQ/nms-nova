#!/usr/bin/env python3
"""NMS-Nova application entrypoint."""

import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from secrets import compare_digest
import yaml
import state.store
from state.alerts import AlertEngine, AlertRule

DEFAULT_RULES = [
    AlertRule(metric_name="cpu_usage_percent", threshold=90.0, comparison="gt", description="CPU critical"),
    AlertRule(metric_name="memory_used_percent", threshold=90.0, comparison="gt", description="Memory critical"),
    AlertRule(metric_name="service_up", threshold=0.5, comparison="lt", description="Service down"),
]
alert_engine = AlertEngine(rules=DEFAULT_RULES)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "state" / "nms-nova.db"

store = state.store.MetricsStore(os.getenv("NMS_DB", str(DEFAULT_DB)))
app = FastAPI(title="NMS-Nova", version="0.1.0")
security = HTTPBasic()

BEARER_TOKEN = os.getenv("NMS_API_TOKEN", "")
WEBHOOK_URL = os.getenv("NMS_WEBHOOK_URL", "")


def _is_api_request(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.startswith("Bearer ") or auth.startswith("Basic ")


def _basic_auth(request: Request) -> bool:
    auth = request.headers.get("authorization")
    if not auth or not auth.startswith("Basic "):
        return False
    import base64

    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
    except Exception:
        return False
    username, _, password = decoded.partition(":")
    expected_user = os.getenv("NMS_AUTH_USER", "admin")
    expected_pass = os.getenv("NMS_AUTH_PASS", "admin")
    return compare_digest(username, expected_user) and compare_digest(password, expected_pass)


def _bearer_auth(request: Request) -> bool:
    if not BEARER_TOKEN:
        return False
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return compare_digest(auth.split(" ", 1)[1], BEARER_TOKEN)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    public_paths = ("/health", "/metrics", "/chart", "/alerts")
    if path in public_paths or any(path.startswith(p) for p in public_paths):
        return await call_next(request)
    if not _is_api_request(request):
        from fastapi.responses import Response
        return Response(headers={"WWW-Authenticate": "Basic"}, status_code=401)
    if _basic_auth(request) or _bearer_auth(request):
        return await call_next(request)
    from fastapi.responses import Response
    return Response(headers={"WWW-Authenticate": "Basic"}, status_code=401)


def _post_webhook(alerts: list[dict[str, Any]]) -> None:
    if not WEBHOOK_URL or not alerts:
        return
    try:
        payload = {"alerts": alerts, "source": "nms-nova"}
        httpx.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception:
        pass


def _evaluate_alerts() -> list[dict[str, Any]]:
    rows = store.latest_samples()
    alerts: list[dict[str, Any]] = []
    for row in rows:
        alerts.extend(
            {"target_name": a.target_name, "metric_name": a.metric_name, "value": a.value, "description": a.description}
            for a in alert_engine.evaluate(row["target_name"], row["metric_name"], row["value"])
        )
    _post_webhook(alerts)
    return alerts


def _render_dashboard() -> str:
    rows = store.latest_samples()
    targets: dict[str, list[dict]] = {}
    for row in rows:
        targets.setdefault(row["target_name"], []).append(row)
    alerts = _evaluate_alerts()

    cfg = yaml.safe_load((BASE_DIR / "targets.yaml").read_text())
    target_map = {}
    for t in cfg.get("targets", []):
        target_map[t["name"]] = t

    tier_map = {name: t.get("tier", "T2") for name, t in target_map.items()}
    cards = []
    for target_name, metrics in sorted(targets.items()):
        items = []
        chart_items = []
        for m in metrics:
            value = m["value"]
            metric_name = m["metric_name"]
            is_error = bool(m.get("error"))
            if metric_name == "service_up":
                unit = ""
                value = "UP" if value == 1.0 else "DOWN"
                color = "#0a0" if value == "UP" else "#a22"
            elif metric_name == "interface_total_kbps":
                unit = " kbps"
                value = f"{value:,.0f}"
                color = "#0a0"
                if is_error:
                    color = "#a22"
            else:
                unit = "%"
                color = "#0a0"
                if is_error:
                    color = "#a22"
                elif isinstance(value, (int, float)):
                    if value >= 90:
                        color = "#a22"
                    elif value >= 70:
                        color = "#b90"
            display = f"{value}{unit}"
            if is_error:
                display += " (error)"
            items.append(
                f"<div class='metric-row'><span class='metric-name'>{metric_name}</span>"
                f"<span class='metric-value' style='color:{color}'>{display}</span></div>"
            )
            if metric_name != "service_up":
                chart_items.append(metric_name)

        chart_html = ""
        if chart_items:
            ranges = ["24h", "7d", "30d"]
            chart_html = (
                "<div class='chart-container' data-target='" + target_name + "' data-range='24h'>"
                "<div class='chart-header'>"
                + "".join(
                    f"<button data-range='{r}' class='range-btn {'active' if r=='24h' else ''}' onclick='window._setRange(\"{target_name}\", \"{r}\")'>{r}</button>"
                    for r in ranges
                )
                + "</div>"
                + "".join(
                    f"<div class='chart-wrap'><canvas id='chart-{target_name}-{m}'></canvas><div class='chart-label'>{m}</div></div>"
                    for m in chart_items
                )
                + "</div>"
            )

        cards.append(
            f"<div class='card'><div class='card-header'><span class='card-title'>{target_name}</span><span class='tier-badge tier-{tier_map.get(target_name, 'T2').lower()}'>{tier_map.get(target_name, 'T2')}</span></div>"
            + "<div class='card-body'>" + "".join(items) + "</div>"
            + chart_html
            + "</div>"
        )

    alert_section = ""
    if alerts:
        alert_section = (
            "<div class='alert-strip'>"
            + "".join(
                f"<div class='alert-item alert-{'critical' if 'down' in a['description'].lower() or 'critical' in a['description'].lower() else 'warning'}'><span class='alert-target'>{a['target_name']}</span><span class='alert-text'>{a['description']}</span><span class='alert-value'>{a['value']}</span></div>"
                for a in alerts
            )
            + "</div>"
        )

    body = alert_section + "<div class='grid'>" + "".join(cards) + "</div>"
    return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>NMS-Nova</title>
  <script src='https://unpkg.com/htmx.org@2.0.0'></script>
  <script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js'></script>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f6f7f9;
      --card-bg: #ffffff;
      --text: #1f2328;
      --muted: #57606a;
      --border: #d0d7de;
      --accent: #0969da;
      --ok: #0a0;
      --warn: #b90;
      --crit: #cf222e;
      --shadow: rgba(31, 35, 40, 0.06);
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0d1117;
        --card-bg: #161b22;
        --text: #c9d1d9;
        --muted: #8b949e;
        --border: #30363d;
        --shadow: rgba(0, 0, 0, 0.4);
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica, Arial, sans-serif; margin: 0; background: var(--bg); color: var(--text); }}
    header {{ padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border); display:flex; justify-content:space-between; align-items:center; gap: 1rem; background: var(--card-bg); }}
    .brand {{ font-weight: 800; letter-spacing: -0.02em; font-size: 1.1rem; }}
    .meta {{ color: var(--muted); font-size: 0.85rem; }}
    main {{ padding: 1.5rem; }}
    .grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
    .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 14px; padding: 1rem; box-shadow: 0 2px 0 var(--shadow); }}
    .card-header {{ display:flex; justify-content:space-between; align-items:center; gap: 0.75rem; padding-bottom: 0.6rem; border-bottom: 1px solid var(--border); margin-bottom: 0.75rem; }}
    .card-title {{ font-weight: 700; font-size: 1rem; word-break: break-word; }}
    .tier-badge {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 0.2rem 0.5rem; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }}
    .tier-t1 {{ color: #1a7f37; border-color: #1a7f37; background: rgba(26,127,55,0.08); }}
    .tier-t2 {{ color: #57606a; }}
    .card-body {{ display: grid; gap: 0.35rem; }}
    .metric-row {{ display: flex; justify-content: space-between; align-items: center; padding: 0.35rem 0; }}
    .metric-name {{ color: var(--muted); font-size: 0.88rem; }}
    .metric-value {{ font-weight: 700; font-size: 1.05rem; letter-spacing: -0.01em; }}
    .chart-container {{ margin-top: 0.9rem; padding-top: 0.7rem; border-top: 1px dashed var(--border); }}
    .chart-header {{ display:flex; gap: 0.4rem; margin-bottom: 0.6rem; }}
    .range-btn {{ background: transparent; border: 1px solid var(--border); border-radius: 8px; padding: 0.25rem 0.55rem; cursor: pointer; font-size: 0.78rem; color: var(--muted); }}
    .range-btn.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
    .chart-wrap {{ display: grid; gap: 0.6rem; }}
    canvas {{ width: 100% !important; height: 110px !important; }}
    .chart-label {{ font-size: 0.75rem; color: var(--muted); text-align: right; }}
    .alert-strip {{ display: grid; gap: 0.5rem; margin-bottom: 1rem; }}
    .alert-item {{ display:flex; justify-content:space-between; align-items:center; gap: 1rem; padding: 0.7rem 0.9rem; border-radius: 10px; border: 1px solid transparent; }}
    .alert-critical {{ background: rgba(207,34,46,0.12); color: var(--crit); border-color: rgba(207,34,46,0.35); }}
    .alert-warning {{ background: rgba(187,144,0,0.10); color: #8a6d00; border-color: rgba(187,144,0,0.35); }}
    .alert-target {{ font-weight: 700; word-break: break-word; }}
    .alert-text {{ color: var(--muted); font-size: 0.9rem; }}
    .alert-value {{ font-weight: 800; font-variant-numeric: tabular-nums; }}
    .empty {{ color: var(--muted); font-size: 0.9rem; }}
  </style>
</head>
<body>
  <header>
    <div><div class='brand'>NMS-Nova</div><div class='meta'>v{app.version}</div></div>
    <div class='meta'>{len(targets)} targets</div>
  </header>
  <main hx-get='/' hx-trigger='every 15s' hx-swap='innerHTML'>
    {body if body else "<div class='empty'>No data yet</div>"}
  </main>
  <script>
    const chartState = {{}};
    function renderCharts() {{
      document.querySelectorAll('.chart-container').forEach(el => {{
        const target = el.dataset.target;
        const range = el.dataset.range || '24h';
        fetch(`/chart/${{encodeURIComponent(target)}}?range=${{range}}`)
          .then(r => r.ok ? r.json() : Promise.reject())
          .then(data => {{
            if (!data || !data.series) return;
            Object.keys(data.series).forEach(metric => {{
              const canvas = document.getElementById(`chart-${{target}}-${{metric}}`);
              if (!canvas) return;
              const points = data.series[metric];
              const labels = points.map(p => p.ts);
              const values = points.map(p => p.value);
              let chart = chartState[`${{target}}-${{metric}}`];
              if (!chart) {{
                const ctx = canvas.getContext('2d');
                chart = new Chart(ctx, {{
                  type: 'line',
                  data: {{ labels, datasets: [{{ label: metric, data: values, borderWidth: 1.5, pointRadius: 2, pointHoverRadius: 4, tension: 0.2 }}] }},
                  options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ display: false }}, y: {{ beginAtZero: true }} }} }}
                }});
                chartState[`${{target}}-${{metric}}`] = chart;
              }} else {{
                chart.data.labels = labels;
                chart.data.datasets[0].data = values;
                chart.update('none');
              }}
            }});
          }})
          .catch(() => {{}});
      }});
    }}
    renderCharts();
    setInterval(renderCharts, 15000);
    window._setRange = function(target, range) {{
      document.querySelectorAll(`.chart-container[data-target=\"${{target}}\"] .range-btn`).forEach(btn => btn.classList.toggle('active', btn.dataset.range === range));
      const el = document.querySelector(`.chart-container[data-target=\"${{target}}\"]`);
      if (el) el.dataset.range = range;
      renderCharts();
    }};
    if (window.htmx) {{
      document.addEventListener('htmx:afterSwap', renderCharts);
    }}
  </script>
</body>
</html>"""


@app.get("/health")
async def health():
    rows = store.latest_samples()
    targets = {}
    for row in rows:
        targets.setdefault(row["target_name"], []).append(row)
    alerts = _evaluate_alerts()
    db_path = Path(os.getenv("NMS_DB", str(DEFAULT_DB)))
    db_size = db_path.stat().st_size if db_path.exists() else 0
    con = __import__("sqlite3").connect(str(db_path))
    try:
        sample_count = con.execute("SELECT count(*) FROM metric_samples").fetchone()[0]
        target_count = con.execute("SELECT count(*) FROM targets").fetchone()[0]
    finally:
        con.close()
    return {
        "status": "ok",
        "version": app.version,
        "targets": targets,
        "alerts": alerts,
        "db": {
            "path": str(db_path),
            "size_bytes": db_size,
            "sample_count": sample_count,
            "target_count": target_count,
        },
    }


@app.get("/alerts")
async def alerts_endpoint():
    rows = store.latest_samples()
    alerts = []
    for row in rows:
        alerts.extend(alert_engine.evaluate(row["target_name"], row["metric_name"], row["value"]))
    return {"alerts": [a.__dict__ for a in alerts]}


@app.get("/chart/{target_name}")
async def target_chart(target_name: str, range: str = "24h"):
    con = __import__("sqlite3").connect(store.db_path)
    con.row_factory = __import__("sqlite3").Row
    try:
        target_row = con.execute("SELECT id FROM targets WHERE name = ?", (target_name,)).fetchone()
        if not target_row:
            return {"error": "not_found"}
        target_id = target_row["id"]

        if range == "7d":
            bucket = "strftime('%Y-%m-%d %H:00:00', timestamp)"
            where = "timestamp >= datetime('now', '-7 days')"
        elif range == "30d":
            bucket = "strftime('%Y-%m-%d', timestamp)"
            where = "timestamp >= datetime('now', '-30 days')"
        else:
            bucket = "strftime('%Y-%m-%d %H:00:00', timestamp)"
            where = "timestamp >= datetime('now', '-24 hours')"

        rows = con.execute(
            f"""
            SELECT {bucket} AS ts, d.name AS metric, avg(s.value) AS value
            FROM metric_samples s
            JOIN metric_definitions d ON d.id = s.definition_id
            WHERE s.target_id = ? AND {where}
            GROUP BY ts, d.name
            ORDER BY ts ASC
            """,
            (target_id,),
        ).fetchall()
        series = {}
        for row in rows:
            series.setdefault(row["metric"], []).append({"ts": row["ts"], "value": round(row["value"], 2)})
        return {"target": target_name, "range": range, "series": series}
    finally:
        con.close()


@app.get("/metrics")
async def metrics_prometheus():
    rows = store.latest_samples()
    lines = ["# NMS-Nova metrics"]
    for row in rows:
        name = row["metric_name"].replace(" ", "_").replace("-", "_").lower()
        target = row["target_name"].replace("-", "_").replace(".", "_")
        lines.append(f'nms_target{{target="{target}",metric="{name}"}} {row["value"]}')
    return HTMLResponse("\n".join(lines), media_type="text/plain")


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_render_dashboard())
