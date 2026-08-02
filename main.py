#!/usr/bin/env python3
"""NMS-Nova application entrypoint."""

import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from secrets import compare_digest
import yaml
import state.store
from state.alerts import AlertEngine, AlertRule

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "state" / "nms-nova.db"

store = state.store.MetricsStore(os.getenv("NMS_DB", str(DEFAULT_DB)))

_initial_alert_rules = [
    AlertRule(metric_name="cpu_usage_percent", threshold=90.0, comparison="gt", description="CPU critical"),
    AlertRule(metric_name="memory_used_percent", threshold=90.0, comparison="gt", description="Memory critical"),
    AlertRule(metric_name="service_up", threshold=0.5, comparison="lt", description="Service down"),
]
try:
    _delivery_init = store.get_delivery_settings()
except Exception:
    _delivery_init = {}
if not _delivery_init:
    store.save_delivery_settings({
        "telegram_enabled": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "telegram_bot_token": TELEGRAM_BOT_TOKEN or "",
        "telegram_chat_id": TELEGRAM_CHAT_ID or "",
        "webhook_enabled": bool(WEBHOOK_URL),
        "webhook_url": WEBHOOK_URL or "",
    })
_delivery_settings = store.get_delivery_settings()
if not store.list_alert_rules():
    for r in _initial_alert_rules:
        store.create_alert_rule(
            metric_name=r.metric_name,
            threshold=r.threshold,
            comparison=r.comparison,
            consecutive=r.consecutive,
            description=r.description,
            enabled=True,
        )
_loaded_rules = [AlertRule(**{k: v for k, v in r.items() if k in {"metric_name", "threshold", "comparison", "consecutive", "description"}}) for r in store.list_alert_rules()] or _initial_alert_rules[:]
alert_engine = AlertEngine(rules=_loaded_rules)
app = FastAPI(title="NMS-Nova", version="0.2.0")
app.mount('/static', StaticFiles(directory='/opt/nms-nova/static'), name='static')
security = HTTPBasic()

BEARER_TOKEN = os.getenv("NMS_API_TOKEN", "")
WEBHOOK_URL = os.getenv("NMS_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


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
    public_paths = ("/health", "/metrics", "/chart")
    if path in public_paths or any(path.startswith(p) for p in public_paths):
        return await call_next(request)
    if not _is_api_request(request):
        from fastapi.responses import Response
        return Response(headers={"WWW-Authenticate": "Basic"}, status_code=401)
    if _basic_auth(request) or _bearer_auth(request):
        return await call_next(request)
    from fastapi.responses import Response
    return Response(headers={"WWW-Authenticate": "Basic"}, status_code=401)


def _load_delivery_settings() -> dict:
    try:
        return store.get_delivery_settings()
    except Exception:
        return {
            "telegram_enabled": False,
            "telegram_bot_token": "",
            "telegram_chat_id": "",
            "webhook_enabled": False,
            "webhook_url": "",
        }

_delivery_settings = _load_delivery_settings()


def _post_webhook(alerts: list[dict[str, Any]]) -> None:
    payload = {"schema_version": 1, "alerts": alerts, "source": "nms-nova"}
    settings = _delivery_settings
    if settings.get("webhook_enabled") and settings.get("webhook_url"):
        try:
            httpx.post(settings["webhook_url"], json=payload, timeout=5)
        except Exception:
            pass
    if settings.get("telegram_enabled") and settings.get("telegram_bot_token") and settings.get("telegram_chat_id") and alerts:
        try:
            text = "\n".join(
                f"⚠️ {a['description']}: {a['target_name']} / {a['metric_name']} = {a['value']}"
                for a in alerts
            )
            httpx.post(
                f"https://api.telegram.org/bot{settings['telegram_bot_token']}/sendMessage",
                json={"chat_id": settings["telegram_chat_id"], "text": text},
                timeout=5,
            )
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
    _post_webhook_with_settings(alerts, _delivery_settings, rules=store.list_alert_rules())
    return alerts


def _render_dashboard() -> str:
    rows = store.latest_samples()
    targets: dict[str, list[dict]] = {}
    for row in rows:
        targets.setdefault(row["target_name"], []).append(row)
    alerts = _evaluate_alerts()

    target_map = {t["name"]: t for t in store.list_targets()}
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
            f"<div class='card'><div class='card-header'><a class='card-title' href='/targets/{target_map[target_name]['id']}' style='text-decoration:none;color:inherit'>{target_name}</a><span class='tier-badge tier-{tier_map.get(target_name, 'T2').lower()}'>{tier_map.get(target_name, 'T2')}</span></div>"
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
    return _layout('Dashboard', body)
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


def _service_status(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "active": False,
        "error": "not checked",
    }


def _get_service_status() -> list[dict[str, Any]]:
    return []


@app.get("/status", response_class=HTMLResponse)
async def status_page():
    db_path = Path(os.getenv("NMS_DB", str(DEFAULT_DB)))
    db_size = db_path.stat().st_size if db_path.exists() else 0
    con = __import__("sqlite3").connect(str(db_path))
    con.row_factory = __import__("sqlite3").Row
    try:
        sample_count = con.execute("SELECT count(*) FROM metric_samples").fetchone()[0]
        target_count = con.execute("SELECT count(*) FROM targets").fetchone()[0]
        latest_row = con.execute("SELECT max(timestamp) AS ts FROM metric_samples").fetchone()
        latest_ts = latest_row["ts"] if latest_row and latest_row["ts"] else None
    finally:
        con.close()
    rows = store.latest_samples()
    alert_count = len(_evaluate_alerts())
    last_seen = f"<span class='metric-value'>{latest_ts}</span>" if latest_ts else "<span class='metric-value'>No samples</span>"
    freshness = (
        "<div class='metric-row'><span class='metric-name'>Latest sample</span>"
        f"{last_seen}</div>"
    )
    body = (
        "<div class='page-header'><h2>Status</h2></div>"
        "<div class='grid'>"
        f"<div class='card'><div class='card-header'><span class='card-title'>System</span></div>"
        f"<div class='card-body'>"
        f"<div class='metric-row'><span class='metric-name'>Version</span><span class='metric-value'>{app.version}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Targets</span><span class='metric-value'>{target_count}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Samples</span><span class='metric-value'>{sample_count}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>DB size</span><span class='metric-value'>{db_size}</span></div>"
        f"{freshness}"
        f"</div></div>"
        f"<div class='card'><div class='card-header'><span class='card-title'>Alerts</span></div>"
        f"<div class='card-body'><div class='metric-row'><span class='metric-name'>Active</span>"
        f"<span class='metric-value'>{alert_count}</span></div></div></div>"
        "</div>"
    )
    return HTMLResponse(_layout("Status", body))


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


# --- Target management UI ---

TARGET_KINDS = ("lxc", "ssh", "docker")
METRIC_OPTIONS = [
    ("cpu_usage_percent", "CPU %"),
    ("memory_used_percent", "Memory %"),
    ("disk_root_used_percent", "Disk %"),
    ("service_up", "Service up"),
    ("load_avg_1m", "Load avg 1m"),
    ("interface_total_kbps", "Interface kbps"),
]


def _target_form(target: dict | None = None, metrics: list[dict] | None = None) -> str:
    name = target.get("name", "") if target else ""
    kind = target.get("kind", "lxc") if target else "lxc"
    address = target.get("address", "") if target else ""
    probe_type = target.get("probe_type", kind) if target else kind
    tier = target.get("tier", "T2") if target else "T2"
    selected_metrics = {m["name"] for m in (metrics or [])}
    metric_checks = "".join(
        "<label><input type='checkbox' name='metrics' value='%s' %s> %s</label>" % (n, "checked" if n in selected_metrics else "", lbl)
        for n, lbl in METRIC_OPTIONS
    )
    ssh_key = target.get("ssh_key", "") if target else ""
    kind_opts = "".join("<option value='%s' %s>%s</option>" % (k, "selected" if kind == k else "", k) for k in TARGET_KINDS)
    probe_opts = "".join("<option value='%s' %s>%s</option>" % (k, "selected" if probe_type == k else "", k) for k in TARGET_KINDS)
    tier_opts = "".join("<option value='%s' %s>%s</option>" % (t, "selected" if tier == t else "", t) for t in ("T1", "T2"))
    if target:
        action = "/targets/%s" % target["id"]
        method = 'hx-put="true"'
    else:
        action = "/targets"
        method = ""
    return """
    <form hx-post='%s' %s hx-target='#main-content' hx-swap='innerHTML'>
      <div class='field'><label>Name</label><input name='name' value='%s' required></div>
      <div class='field'><label>Kind</label><select name='kind'>%s</select></div>
      <div class='field'><label>Address</label><input name='address' value='%s' required></div>
      <div class='field'><label>Probe type</label><select name='probe_type'>%s</select></div>
      <div class='field'><label>Tier</label><select name='tier'>%s</select></div>
      <div class='field'><label>SSH key path</label><input name='ssh_key' value='%s'></div>
      <div class='field'><label>Metrics</label><div class='checks'>%s</div></div>
      <button type='submit'>Save</button> <button type='button' hx-get='/targets' hx-target='#main-content' hx-swap='innerHTML'>Cancel</button>
    </form>
    """ % (action, method, name, kind_opts, address, probe_opts, tier_opts, ssh_key, metric_checks)




@app.get("/settings-v2")
async def settings_v2():
    s = store.get_delivery_settings()
    masked_token = "••••••••" if s.get("telegram_bot_token") else ""
    masked_chat = "••••••••" if s.get("telegram_chat_id") else ""
    masked_webhook = "••••••••" if s.get("webhook_url") else ""
    body = (
        "<div class='page-header'><h2>Alert delivery</h2></div>"
        "<div class='grid'>"
        "<div class='card'><div class='card-header'><span class='card-title'>Telegram</span></div>"
        "<div class='card-body'>"
        "<form hx-post='/settings-v2/delivery' hx-target='#main-content' hx-swap='innerHTML'>"
        f"<div class='field'><label>Enable Telegram</label><select name='telegram_enabled'>"
        f"<option value='1' {'selected' if s.get('telegram_enabled') else ''}>Yes</option>"
        f"<option value='0' {'selected' if not s.get('telegram_enabled') else ''}>No</option>"
        "</select></div>"
        f"<div class='field'><label>Bot token</label><input type='password' name='telegram_bot_token' value='' placeholder='{masked_token}' autocomplete='new-password'></div>"
        f"<div class='field'><label>Chat ID</label><input name='telegram_chat_id' value='{masked_chat if s.get('telegram_chat_id') else ''}'></div>"
        "<input type='hidden' name='_csrf' value='{{csrf}}'><button type='submit'>Save</button></form></div></div>"
        "<div class='card'><div class='card-header'><span class='card-title'>Webhook</span></div>"
        "<div class='card-body'>"
        "<form hx-post='/settings-v2/delivery' hx-target='#main-content' hx-swap='innerHTML'>"
        f"<div class='field'><label>Enable webhook</label><select name='webhook_enabled'>"
        f"<option value='1' {'selected' if s.get('webhook_enabled') else ''}>Yes</option>"
        f"<option value='0' {'selected' if not s.get('webhook_enabled') else ''}>No</option>"
        "</select></div>"
        f"<div class='field'><label>Webhook URL</label><input name='webhook_url' value='{masked_webhook if s.get('webhook_url') else ''}'></div>"
        "<input type='hidden' name='_csrf' value='{{csrf}}'><button type='submit'>Save</button></form></div></div>"
        "<div id='test-result'></div>"
        "<div class='card'><div class='card-header'><span class='card-title'>Test</span></div>"
        "<div class='card-body'><button class='button' hx-post='/settings-v2/test' hx-target='#test-result' hx-swap='innerHTML'>Send test alert</button></div></div>"
        "<input type='hidden' name='_csrf' value='{{csrf}}'>"
        "</div>"
    )
    return HTMLResponse(_layout("Alert delivery", body), status_code=200)


@app.post("/settings-v2/delivery")
async def save_delivery_v2(request: Request):
    form = await request.form()
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    settings = {
        "telegram_enabled": form.get("telegram_enabled") == "1",
        "telegram_bot_token": form.get("telegram_bot_token", ""),
        "telegram_chat_id": form.get("telegram_chat_id", ""),
        "webhook_enabled": form.get("webhook_enabled") == "1",
        "webhook_url": form.get("webhook_url", ""),
    }
    store.save_delivery_settings(settings)
    global _delivery_settings
    _delivery_settings = settings
    return HTMLResponse(_post_save_redirect("/settings-v2"))


@app.post("/settings-v2/test")
async def test_delivery_v2(request: Request):
    form = await request.form()
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    settings = store.get_delivery_settings()
    test_alerts = [
        {"target_name": "test",
         "metric_name": "test_metric",
         "value": 1,
         "description": "Test alert delivery"},
    ]
    _post_webhook_with_settings(test_alerts, settings)
    recent = store._conn().execute("SELECT destination, status, error, created_at FROM delivery_log ORDER BY id DESC LIMIT 2").fetchall()
    rows = "".join(
        f"<div class='metric-row'><span class='metric-name'>{r[0]}</span><span class='metric-value'>{'OK' if r[1] and r[1] < 400 else 'FAIL'} {r[1] or 0}</span></div>"
        + (f"<div class='empty' style='font-size:0.8rem'>{r[2]}</div>" if r[2] else "")
        for r in recent
    )
    return HTMLResponse(f"<div class='empty'>Test complete</div>{rows}")


@app.get("/settings")
async def settings_form():
    s = store.get_delivery_settings()
    body = (
        "<div class='page-header'><h2>Alert delivery</h2></div>"
        "<div class='grid'>"
        "<div class='card'><div class='card-header'><span class='card-title'>Telegram</span></div>"
        "<div class='card-body'>"
        "<form hx-post='/settings/delivery' hx-target='#main-content' hx-swap='innerHTML'>"
        f"<div class='field'><label>Enable Telegram</label><select name='telegram_enabled'>"
        f"<option value='1' {'selected' if s.get('telegram_enabled') else ''}>Yes</option>"
        f"<option value='0' {'selected' if not s.get('telegram_enabled') else ''}>No</option>"
        "</select></div>"
        f"<div class='field'><label>Bot token</label><input name='telegram_bot_token' value='{s.get('telegram_bot_token','')}'></div>"
        f"<div class='field'><label>Chat ID</label><input name='telegram_chat_id' value='{s.get('telegram_chat_id','')}'></div>"
        "<button type='submit'>Save</button></form></div></div>"
        "<div class='card'><div class='card-header'><span class='card-title'>Webhook</span></div>"
        "<div class='card-body'>"
        "<form hx-post='/settings/delivery' hx-target='#main-content' hx-swap='innerHTML'>"
        f"<div class='field'><label>Enable webhook</label><select name='webhook_enabled'>"
        f"<option value='1' {'selected' if s.get('webhook_enabled') else ''}>Yes</option>"
        f"<option value='0' {'selected' if not s.get('webhook_enabled') else ''}>No</option>"
        "</select></div>"
        f"<div class='field'><label>Webhook URL</label><input name='webhook_url' value='{s.get('webhook_url','')}'></div>"
        f"<div class='field'><label>Webhook secret (optional HMAC)</label><input type='password' name='webhook_secret' value='' placeholder='{'••••••••' if s.get('webhook_secret') else ''}' autocomplete='new-password'></div>"
        "<input type='hidden' name='_csrf' value='{{csrf}}'><button type='submit'>Save</button></form></div></div>"
        "<div id='test-result'></div>"
        "<div class='card'><div class='card-header'><span class='card-title'>Test</span></div>"
        "<div class='card-body'><button class='button' hx-post='/settings/test' hx-target='#test-result' hx-swap='innerHTML'>Send test alert</button></div></div>"
        "<input type='hidden' name='_csrf' value='{{csrf}}'>"
        "</div>"
    )
    return HTMLResponse(_layout("Alert delivery", body))


@app.post("/settings/delivery")
async def save_delivery(request: Request):
    form = await request.form()
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    settings = {
        "telegram_enabled": form.get("telegram_enabled") == "1",
        "telegram_bot_token": form.get("telegram_bot_token", ""),
        "telegram_chat_id": form.get("telegram_chat_id", ""),
        "webhook_enabled": form.get("webhook_enabled") == "1",
        "webhook_url": form.get("webhook_url", ""),
        "webhook_secret": form.get("webhook_secret", ""),
    }
    store.save_delivery_settings(settings)
    global _delivery_settings
    _delivery_settings = settings
    return HTMLResponse(_post_save_redirect("/settings"))


@app.post("/settings/test")
async def test_delivery(request: Request):
    form = await request.form()
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    import time as _time
    token = request.cookies.get("_csrf", "")
    now = _time.time()
    last = _last_test_ts.get(token, 0)
    if now - last < 60:
        return HTMLResponse("<div class='empty'>Rate limited. Wait 60 seconds before another test.</div>", status_code=429)
    _last_test_ts[token] = now
    settings = store.get_delivery_settings()
    test_alerts = [{
        "target_name": "test",
        "metric_name": "test_metric",
        "value": 1,
        "description": "Test alert delivery",
    }]
    _post_webhook_with_settings(test_alerts, settings, rules=store.list_alert_rules())
    return HTMLResponse("<div class='empty'>Test sent. Check your Telegram/webhook destination.</div>")


def _post_webhook_with_settings(alerts: list[dict[str, Any]], settings: dict, rules: list[dict[str, Any]] | None = None) -> None:
    if not alerts:
        return
    # Alert dedup by (target, metric) within a 15-minute window
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for a in alerts:
        key = (str(a.get("target_name")), str(a.get("metric_name")), str(a.get("description")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    if not deduped:
        return

    # Per-rule routing: filter alerts by rule.delivery if rules are provided
    telegram_alerts: list[dict[str, Any]] = []
    webhook_alerts: list[dict[str, Any]] = []
    if rules:
        rule_map = {r["metric_name"]: r for r in rules}
        for a in deduped:
            rule = rule_map.get(a.get("metric_name"))
            delivery = (rule or {}).get("delivery", "all")
            if delivery == "telegram":
                telegram_alerts.append(a)
            elif delivery == "webhook":
                webhook_alerts.append(a)
            else:
                telegram_alerts.append(a)
                webhook_alerts.append(a)
    else:
        telegram_alerts = deduped[:]
        webhook_alerts = deduped[:]

    destinations: list[tuple[str, str, dict]] = []
    if settings.get("webhook_enabled") and settings.get("webhook_url") and webhook_alerts:
        payload = {"schema_version": 1, "alerts": webhook_alerts, "source": "nms-nova"}
        if settings.get("webhook_secret"):
            import hmac, hashlib, base64
            sig = hmac.new(settings["webhook_secret"].encode(), base64.b64encode(str(payload).encode()), hashlib.sha256).hexdigest()
            payload = dict(payload)
            payload["hmac"] = sig
        destinations.append(("webhook", settings["webhook_url"], payload))
    if settings.get("telegram_enabled") and settings.get("telegram_bot_token") and settings.get("telegram_chat_id") and telegram_alerts:
        text_out = "\n".join(
            f"⚠️ {a['description']}: {a['target_name']} / {a['metric_name']} = {a['value']}"
            for a in telegram_alerts
        )
        destinations.append(("telegram", f"https://api.telegram.org/bot{settings['telegram_bot_token']}/sendMessage", {"chat_id": settings["telegram_chat_id"], "text": text_out}))

    for kind, url, payload_or_json in destinations:
        status = 0
        error_text = None
        for attempt in range(2):
            try:
                resp = httpx.post(url, json=payload_or_json, timeout=8)
                status = resp.status_code
                if resp.status_code < 400:
                    break
                error_text = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:
                status = 0
                error_text = str(exc)[:200]
        try:
            store.log_delivery(kind, len(deduped), status, error_text)
        except Exception:
            pass


@app.get("/alerts")
async def list_alerts_ui():
    rules = store.list_alert_rules()
    cards = "".join(
        f"<div class='card'><div class='card-header'><span class='card-title'>{r['metric_name']}</span>"
        f"<span class='tier-badge tier-t2'>{'Enabled' if r['enabled'] else 'Disabled'}</span></div>"
        f"<div class='card-body'>"
        f"<div class='metric-row'><span class='metric-name'>Threshold</span><span class='metric-value'>{r['threshold']}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Compare</span><span class='metric-value'>{r['comparison']}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Consecutive</span><span class='metric-value'>{r['consecutive']}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Description</span><span class='metric-value'>{r['description'] or '-'}</span></div>"
        f"</div>"
        f"<div class='actions'>"
        f"<a class='button' href='/alerts/{r['id']}/edit'>Edit</a> "
        f"<button class='button' hx-delete='/alerts/{r['id']}' hx-confirm='Delete {r['metric_name']} rule?' hx-target='#main-content' hx-swap='innerHTML'>Delete</button>"
        f"</div></div></div>"
        for r in rules
    )
    body = (
        "<div class='page-header'><h2>Alert rules</h2><button hx-get='/alerts/new' hx-target='#main-content' hx-swap='innerHTML'>Add rule</button></div>"
        "<div class='grid'>" + (cards or "<div class='empty'>No rules</div>") + "</div>"
    )
    return HTMLResponse(_layout("Alerts", body))


@app.get("/alerts/new")
async def new_alert_form():
    return HTMLResponse(_layout("New alert rule", _alert_rule_form()))


@app.get("/alerts/{rule_id}/edit")
async def edit_alert_form(rule_id: int):
    rule = next((r for r in store.list_alert_rules() if r["id"] == rule_id), None)
    if not rule:
        return HTMLResponse(_layout("Not found", "<div class='empty'>Not found</div>"), status_code=404)
    return HTMLResponse(_layout("Edit alert rule", _alert_rule_form(rule=rule)))


@app.post("/alerts")
async def create_alert(request: Request):
    form = await request.form()
    store.create_alert_rule(
        metric_name=form.get("metric_name", ""),
        threshold=float(form.get("threshold", 0)),
        comparison=form.get("comparison", "gt"),
        consecutive=int(form.get("consecutive", 2)),
        description=form.get("description", ""),
        enabled=bool(int(form.get("enabled", 1))),
    )
    _refresh_alert_engine()
    return HTMLResponse(_post_save_redirect("/alerts"))


@app.put("/alerts/{rule_id}")
async def update_alert(rule_id: int, request: Request):
    rule = next((r for r in store.list_alert_rules() if r["id"] == rule_id), None)
    if not rule:
        return HTMLResponse(_layout("Not found", "<div class='empty'>Not found</div>"), status_code=404)
    form = await request.form()
    store.update_alert_rule(
        rule_id,
        metric_name=form.get("metric_name", rule["metric_name"]),
        threshold=float(form.get("threshold", rule["threshold"])),
        comparison=form.get("comparison", rule["comparison"]),
        consecutive=int(form.get("consecutive", rule["consecutive"])),
        description=form.get("description", rule["description"]),
        enabled=bool(int(form.get("enabled", rule["enabled"]))),
    )
    _refresh_alert_engine()
    return HTMLResponse(_post_save_redirect("/alerts"))


@app.delete("/alerts/{rule_id}")
async def delete_alert(rule_id: int):
    store.delete_alert_rule(rule_id)
    _refresh_alert_engine()
    return HTMLResponse(_post_save_redirect("/alerts"))


def _refresh_alert_engine() -> None:
    rules = [AlertRule(**r) for r in store.list_alert_rules()]
    alert_engine.rules = rules or _initial_alert_rules[:]


def _alert_rule_form(rule: Optional[dict] = None) -> str:
    rule = rule or {}
    rid = rule.get("id", "")
    action = f"/alerts/{rid}" if rid else "/alerts"
    method = 'hx-put="true"' if rid else ""
    comparison = rule.get("comparison", "gt")
    enabled = 1 if rule.get("enabled", True) else 0
    return f"""
    <form hx-post='{action}' {method} hx-target='#main-content' hx-swap='innerHTML'>
      <div class='field'><label>Metric</label><input name='metric_name' value='{rule.get('metric_name','')}' required></div>
      <div class='field'><label>Threshold</label><input name='threshold' type='number' step='any' value='{rule.get('threshold','')}' required></div>
      <div class='field'><label>Comparison</label><select name='comparison'>
        <option value='gt' {'selected' if comparison=='gt' else ''}>gt</option>
        <option value='lt' {'selected' if comparison=='lt' else ''}>lt</option>
        <option value='eq' {'selected' if comparison=='eq' else ''}>eq</option>
      </select></div>
      <div class='field'><label>Consecutive</label><input name='consecutive' type='number' value='{rule.get('consecutive', 2)}' required></div>
      <div class='field'><label>Description</label><input name='description' value='{rule.get('description','')}'></div>
      <div class='field'><label>Enabled</label><select name='enabled'>
        <option value='1' {'selected' if enabled else ''}>Yes</option>
        <option value='0' {'selected' if not enabled else ''}>No</option>
      </select></div>
      <button type='submit'>Save</button> <button type='button' hx-get='/alerts' hx-target='#main-content' hx-swap='innerHTML'>Cancel</button>
    </form>
    """

@app.get("/targets")
async def list_targets_ui():
    rows = store.list_targets()
    cards = "".join(
        f"<div class='card'><div class='card-header'><span class='card-title'>{t['name']}</span>"
        f"<span class='tier-badge tier-{t.get('tier','T2').lower()}'>{t.get('tier','T2')}</span></div>"
        f"<div class='card-body'><div class='card-meta'><a class='card-link' href='/targets/{t['id']}'>{t['name']}</a></div>"
        f"<div class='card-meta'>{t.get('kind','')} / {t.get('address','')}</div>"
        f"<div class='actions'><a class='button' href='/targets/{t['id']}'>View</a> "
        f"<a class='button' href='/targets/{t['id']}/edit'>Edit</a> "
        f"<button class='button' hx-delete='/targets/{t['id']}' hx-confirm='Delete {t['name']}?' hx-target='#main-content' hx-swap='innerHTML'>Delete</button></div></div></div>"
        for t in rows
    )
    body = (
        "<div class='page-header'><h2>Targets</h2><button hx-get='/targets/new' hx-target='#main-content' hx-swap='innerHTML'>Add target</button></div>"
        "<div class='grid'>" + (cards or "<div class='empty'>No targets</div>") + "</div>"
    )
    return HTMLResponse(_layout("Targets", body))


@app.get("/targets/{target_id}")
async def target_detail(target_id: int):
    target = store.get_target(target_id)
    if not target:
        return HTMLResponse(_layout("Not found", "<div class='empty'>Not found</div>"), status_code=404)
    rows = store.latest_samples()
    target_rows = [r for r in rows if r.get("target_name") == target.get("name")]
    target_metric_names = {r.get("metric_name") for r in target_rows}
    chart_metrics = [m for m in target_metric_names if m != "service_up"]
    items = []
    chart_items = []
    for row in target_rows:
        value = row.get("value")
        metric_name = row.get("metric_name")
        is_error = bool(row.get("error"))
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
            "<div class='chart-container' data-target='" + target["name"] + "' data-range='24h'>"
            "<div class='chart-header'>"
            + "".join(
                f"<button data-range='{r}' class='range-btn {'active' if r=='24h' else ''}' onclick='window._setRange(\"{target['name']}\", \"{r}\")'>{r}</button>"
                for r in ranges
            )
            + "</div>"
            + "".join(
                f"<div class='chart-wrap'><canvas id='chart-{target['name']}-{m}'></canvas><div class='chart-label'>{m}</div></div>"
                for m in chart_items
            )
            + "</div>"
        )
    body = (
        "<div class='page-header'><h2>" + target["name"] + "</h2>"
        "<div class='actions'><a class='button' href='/targets/" + str(target["id"]) + "/edit'>Edit</a> "
        "<a class='button' href='/targets'>Back</a></div></div>"
        "<div class='grid'><div class='card'><div class='card-header'><span class='card-title'>Target</span></div>"
        "<div class='card-body'>"
        f"<div class='metric-row'><span class='metric-name'>Kind</span><span class='metric-value'>{target.get('kind','')}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Address</span><span class='metric-value'>{target.get('address','')}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Probe type</span><span class='metric-value'>{target.get('probe_type','')}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Tier</span><span class='metric-value'>{target.get('tier','T2')}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>SSH key path</span><span class='metric-value' style='word-break:break-all'>{target.get('ssh_key','') or '-'}</span></div>"
        "</div></div>"
        "<div class='card'><div class='card-header'><span class='card-title'>Latest metrics</span></div>"
        "<div class='card-body'>" + ("".join(items) if items else "<div class='empty'>No samples yet</div>") + "</div></div>"
        "</div>"
        + chart_html
    )
    return HTMLResponse(_layout(target["name"], body))


@app.get("/targets/new")
async def new_target_form():
    return HTMLResponse(_layout("New target", _target_form()))


@app.get("/targets/{target_id}/edit")
async def edit_target_form(target_id: int):
    target = store.get_target(target_id)
    if not target:
        return HTMLResponse(_layout("Not found", "<div class='empty'>Not found</div>"), status_code=404)
    metrics = store.list_metrics_for_target(target_id)
    return HTMLResponse(_layout("Edit " + target["name"], _target_form(target=target, metrics=metrics)))


@app.post("/targets")
async def create_target(request: Request):
    form = await request.form()
    target_id = store.create_target(
        name=form.get("name", ""),
        kind=form.get("kind", "lxc"),
        address=form.get("address", ""),
        probe_type=form.get("probe_type", form.get("kind", "lxc")),
        tier=form.get("tier", "T2"),
        ssh_key=form.get("ssh_key"),
    )
    metrics = form.getlist("metrics")
    for name in metrics:
        store.create_metric(target_id, name=name, unit=None, poll_interval_sec=60)
    return HTMLResponse(_post_save_redirect(f"/targets/{target_id}/edit"))


@app.put("/targets/{target_id}")
async def update_target(target_id: int, request: Request):
    target = store.get_target(target_id)
    if not target:
        return HTMLResponse("<div class='empty'>Not found</div>", status_code=404)
    form = await request.form()
    store.update_target(
        target_id,
        name=form.get("name", target["name"]),
        kind=form.get("kind", target["kind"]),
        address=form.get("address", target["address"]),
        probe_type=form.get("probe_type", form.get("kind")),
        tier=form.get("tier", target.get("tier", "T2")),
        ssh_key=form.get("ssh_key", target.get("ssh_key")),
    )
    existing = {m["name"] for m in store.list_metrics_for_target(target_id)}
    requested = set(form.getlist("metrics"))
    for name in existing - requested:
        for m in store.list_metrics_for_target(target_id):
            if m["name"] == name:
                store.delete_metric(m["id"])
    for name in requested - existing:
        store.create_metric(target_id, name=name, unit=None, poll_interval_sec=60)
    return HTMLResponse(_post_save_redirect(f"/targets/{target_id}/edit"))


@app.delete("/targets/{target_id}")
async def delete_target(target_id: int):
    store.delete_target(target_id)
    return HTMLResponse(_post_save_redirect("/targets"))


def _post_save_redirect(location: str) -> str:
    return f"<div hx-redirect='{location}'></div>"


def _layout(title: str, body: str, status_code: int = 200) -> str:
    import secrets
    csrf = secrets.token_urlsafe(16)
    return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>NMS-Nova - {title}</title>
  <script src='https://unpkg.com/htmx.org@2.0.0'></script>
  <script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js'></script>
  <script src='/static/detail.js'></script>
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
    .page-header {{ display:flex; justify-content:space-between; align-items:center; gap: 1rem; margin-bottom: 1rem; }}
    .grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
    .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 14px; padding: 1rem; box-shadow: 0 2px 0 var(--shadow); }}
    .card-header {{ display:flex; justify-content:space-between; align-items:center; gap: 0.75rem; padding-bottom: 0.6rem; border-bottom: 1px solid var(--border); margin-bottom: 0.75rem; }}
    .card-title {{ font-weight: 700; font-size: 1rem; word-break: break-word; }}
    .tier-badge {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 0.2rem 0.5rem; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }}
    .tier-t1 {{ color: #1a7f37; border-color: #1a7f37; background: rgba(26,127,55,0.08); }}
    .tier-t2 {{ color: #57606a; }}
    .card-meta {{ color: var(--muted); font-size: 0.85rem; word-break: break-all; }}
    .actions {{ display:flex; gap: 0.5rem; margin-top: 0.75rem; flex-wrap: wrap; }}
    .field {{ display:flex; flex-direction: column; gap: 0.35rem; margin-bottom: 0.9rem; }}
    .field label {{ font-size: 0.85rem; color: var(--muted); }}
    .field input, .field select {{ padding: 0.55rem 0.6rem; border-radius: 10px; border: 1px solid var(--border); background: transparent; color: var(--text); }}
    .checks {{ display: grid; gap: 0.35rem; }}
    .card-link {{ color: var(--accent); text-decoration: none; }}
    .metric-row {{ display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; padding: 0.35rem 0; }}
    .metric-name {{ color: var(--muted); font-size: 0.85rem; }}
    .metric-value {{ font-weight: 700; font-size: 1.05rem; letter-spacing: -0.01em; }}
    button, .button {{ padding: 0.55rem 0.75rem; border-radius: 10px; border: 1px solid var(--border); background: var(--card-bg); color: var(--text); cursor: pointer; }}
    .empty {{ color: var(--muted); }}
    .nav-toggle {{ display: none; }}
    nav {{ display: block; }}
    nav.open {{ display:block; margin-top: 0.75rem; }}
    @media (max-width: 640px) {{
      .nav-toggle {{ display: inline-block; }}
      nav {{ display:none; }}
      nav.open {{ display:block; margin-top: 0.75rem; }}
      nav a {{ display:block; margin: 0.35rem 0; }}
      form > div, form {{ width: 100%; }}
      .field input, .field select {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class='topbar'>
      <a class='brand' href='/'>NMS-Nova</a>
      <button class='nav-toggle' id='nav-toggle' aria-expanded='false' aria-controls='main-nav'>Menu</button>
    </div>
    <nav id='main-nav'>
      <a href='/'>Dashboard</a>
      <a href='/targets'>Targets</a>
      <a href='/alerts'>Alerts</a>
      <a href='/settings-v2'>Settings</a>
    </nav>
  </header>
  <main id='main-content'>
    {body}
  </main>
  <script>
    (function(){{
      const path = window.location.pathname || "/";
      document.querySelectorAll("nav a").forEach(function(a){{
        const href = a.getAttribute("href") || "/";
        const active = (href === "/" && path === "/") || (href !== "/" && path.startsWith(href));
        if (active) a.classList.add("active");
      }});
      if (!document.cookie.includes("_csrf=")) {{
        document.cookie = "_csrf={{csrf}}; Path=/; SameSite=Strict";
      }}
    }})();
    (function(){{
      const btn = document.getElementById("nav-toggle");
      const nav = document.getElementById("main-nav");
      if (!btn || !nav) return;
      btn.addEventListener("click", function(){{
        const open = nav.classList.toggle("open");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      }});
    }})();
  </script>
</body>
</html>"""


# ---------------------------
# M12: /api/v1 JSON endpoints
# ---------------------------
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/targets")
def api_list_targets():
    rows = store.list_targets()
    return JSONResponse([dict(r) for r in rows])


@api_router.get("/targets/{target_id}")
def api_get_target(target_id: int):
    row = store.get_target(target_id)
    if not row:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse(dict(row))


@api_router.get("/targets/{target_id}/metrics")
def api_get_target_metrics(target_id: int):
    rows = store.list_metric_definitions(target_id)
    return JSONResponse([dict(r) for r in rows])


@api_router.get("/metrics")
def api_list_metrics():
    con = store._connect()
    try:
        rows = con.execute("""
            SELECT ms.id, ms.target_id, t.name AS target_name, ms.definition_id,
                   md.name AS metric_name, md.unit, ms.value, ms.timestamp
            FROM metric_samples ms
            JOIN targets t ON t.id = ms.target_id
            JOIN metric_definitions md ON md.id = ms.definition_id
            ORDER BY ms.timestamp DESC
            LIMIT 500
        """).fetchall()
        return JSONResponse([dict(r) for r in rows])
    finally:
        con.close()


@api_router.get("/alerts/rules")
def api_list_alert_rules():
    rows = store.list_alert_rules()
    return JSONResponse([dict(r) for r in rows])


@api_router.get("/alerts/delivery")
def api_get_delivery_settings():
    settings = store.get_delivery_settings()
    return JSONResponse({
        "telegram_enabled": bool(settings.get("telegram_enabled")),
        "webhook_enabled": bool(settings.get("webhook_enabled")),
        "webhook_url": settings.get("webhook_url", ""),
    })


@api_router.get("/alerts/delivery/log")
def api_delivery_log(limit: int = 100):
    rows = store.recent_delivery_log(limit)
    return JSONResponse([dict(r) for r in rows])


app.include_router(api_router)
