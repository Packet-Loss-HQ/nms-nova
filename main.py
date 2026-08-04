#!/usr/bin/env python3
"""NMS-Nova application entrypoint."""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional
from fastapi import HTTPException, Request

import httpx
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from secrets import compare_digest
import yaml
import state.store
from state import license as nms_license


def _require_feature(feature: str):
    lic = _load_license()
    if not nms_license.is_enabled(lic, feature):
        raise HTTPException(status_code=403, detail={
            "error": "feature_not_available",
            "feature": feature,
            "license_mode": lic.mode,
            "message": nms_license.feature_not_available_message(feature, lic.mode),
        })
from state.alerts import AlertEngine, AlertRule

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "state" / "nms-nova.db"

store = state.store.MetricsStore(os.getenv("NMS_DB", str(DEFAULT_DB)))
try:
    store.migrate_add_alert_rule_delivery_columns()
except Exception:
    pass
try:
    store.migrate_add_delivery_columns()
except Exception:
    pass
try:
    _api_tokens_cache = store.list_api_tokens()
except Exception:
    _api_tokens_cache = []

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
app = FastAPI(title="NMS-Nova", docs_url="/docs", redoc_url="/redoc", version="0.4.0")
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')
security = HTTPBasic()


class HTMXFragmentMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.headers.get("hx-request") and response.headers.get("content-type", "").startswith("text/html"):
            try:
                body = response.body
                if isinstance(body, bytes):
                    text = body.decode("utf-8", errors="replace")
                    start = text.find("<main id='main-content'>")
                    end = text.find("</main>", start)
                    if start != -1 and end != -1:
                        inner = text[start + len("<main id='main-content'>"):end].strip()
                        return HTMLResponse(inner, status_code=response.status_code)
            except Exception:
                pass
        return response


app.add_middleware(HTMXFragmentMiddleware)

BEARER_TOKEN = os.getenv("NMS_API_TOKEN", "")
WEBHOOK_URL = os.getenv("NMS_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _is_api_request(req: Request) -> bool:
    auth = req.headers.get("authorization", "")
    return auth.startswith("Bearer ") or auth.startswith("Basic ")


def _is_public_path(path: str) -> bool:
    public_prefixes = (
        "/", "/health", "/healthz", "/metrics", "/chart",
        "/static", "/api/v1", "/docs", "/redoc", "/openapi.json", "/license/check", "/setup"
    )
    return path in public_prefixes or any(path.startswith(p) for p in public_prefixes)


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


# M13: scoped API token auth
try:
    api_tokens = store.list_api_tokens()
except Exception:
    api_tokens = _api_tokens_cache


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if _is_public_path(path):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
        scopes = [t["scope"] for t in api_tokens if t.get("token") == token and t.get("enabled")]
        if scopes:
            request.state.api_scopes = scopes
            return await call_next(request)
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
        reliability = None
        target_id_for_card = None
        for m in metrics:
            value = m["value"]
            metric_name = m["metric_name"]
            is_error = bool(m.get("error"))
            if metric_name == "service_up":
                unit = ""
                value = "UP" if value == 1.0 else "DOWN"
                color = "#0a0" if value == "UP" else "#a22"
            elif metric_name == "interface_total_kbps":
                _v = value if isinstance(value, (int, float)) else 0
                if _v >= 1_000_000:
                    value = f"{_v/1_000_000:,.2f}"
                    unit = " Gbps"
                elif _v >= 1_000:
                    value = f"{_v/1_000:,.2f}"
                    unit = " Mbps"
                else:
                    value = f"{_v:,.0f}"
                    unit = " kbps"
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
            if target_id_for_card is None:
                target_id_for_card = m.get("target_id")
        if target_id_for_card is not None:
            reliability = store.probe_reliability(target_id_for_card)

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

        reliability_badge = ""
        if reliability is not None:
            rel_class = "rel-ok" if reliability["success_rate"] >= 95 else "rel-warn" if reliability["success_rate"] >= 80 else "rel-error"
            reliability_badge = f"<span class='reliability-badge {rel_class}'>{reliability['success_rate']:.0f}% probe success</span>"
        cards.append(
            f"<div class='card'><div class='card-header'><a class='card-title' href='/targets/{target_map[target_name]['id']}' style='text-decoration:none;color:inherit'>{target_name}</a>{reliability_badge}<span class='tier-badge tier-{tier_map.get(target_name, 'T2').lower()}'>{tier_map.get(target_name, 'T2')}</span></div>"
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

    if not cards:
        body = "<div class='empty'><p>No targets yet.</p><a class='button primary' href='/setup'>Go to Setup</a></div>"
    else:
        body = alert_section + "<div class='grid'>" + "".join(cards) + "</div>"
    return _layout('Dashboard', body)
@app.get("/healthz")
async def healthz():
    return JSONResponse({"status": "ok"})


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
            bucket = "strftime('%Y-%m-%d', timestamp)"
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

@app.get("/setup")
async def setup():
    body = """
    <div class='page-header'><h2>Setup</h2></div>
    <div class='grid'>
      <div class='card'>
        <div class='card-header'><div class='card-title'>Quick start</div></div>
        <div class='card-body'>
          <p class='empty'>Add your first target, then return here to see live data.</p>
          <a class='button primary' href='/targets/new'>Add target</a>
        </div>
      </div>
      <div class='card'>
        <div class='card-header'><div class='card-title'>Demo mode</div></div>
        <div class='card-body'>
          <p class='empty'>Generate sample data to explore the UI without real probes.</p>
          <button class='primary' hx-post='/setup/demo' hx-target='#main-content' hx-swap='innerHTML'>Load demo data</button>
        </div>
      </div>
    </div>
    """
    return HTMLResponse(_layout("Setup", body))

@app.post("/setup/demo")
async def setup_demo():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("seed_demo_data", "/opt/nms-nova/scripts/seed_demo_data.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
        msg = "<div class='empty'>Demo data loaded. Go to <a href='/'>Dashboard</a>.</div>"
    except Exception as exc:
        msg = f"<div class='empty'>Demo load failed: {exc}</div>"
    return HTMLResponse(msg)


PUBLIC_ROUTES = {"/", "/metrics", "/chart", "/health", "/healthz", "/setup"}
PUBLIC_PREFIXES = ("/static/", "/setup", "/setup/")


def _is_public(path: str) -> bool:
    if path in PUBLIC_ROUTES:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


@app.middleware("http")
async def web_auth_middleware(request: Request, call_next):
    path = request.url.path
    if not _is_public(path):
        settings = store.get_settings()
        if settings.get("web_auth_enabled") and settings.get("web_password_hash"):
            auth = request.headers.get("authorization", "")
            try:
                decoded = __import__("base64").b64decode(auth.split(" ", 1)[1]).decode()
                username, password = decoded.split(":", 1)
            except Exception:
                username = password = None
            if username != "nms-nova" or __import__("hashlib").sha256(password.encode()).hexdigest() != settings["web_password_hash"]:
                return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Basic"})
    return await call_next(request)




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
      <button type='submit' class='primary'>Save</button> <button type='button' hx-get='/targets' hx-target='#main-content' hx-swap='innerHTML'>Cancel</button>
    </form>
    """ % (action, method, name, kind_opts, address, probe_opts, tier_opts, ssh_key, metric_checks)




@app.get("/settings")
async def settings_form():
    delivery = store.get_delivery_settings()
    general = store.get_settings()
    retention = general.get("retention_days", 30)
    masked = "••••••••" if general.get("web_password_hash") else ""
    brand = store.get_branding_settings()
    banner = _upgrade_banner(brand.get("license_mode", "mit"))
    body = (
        f"{banner}"
        "<div class='page-header'><h2>Settings</h2></div>"
        "<div class='grid'>"
        "<div class='card'><div class='card-header'><div class='card-title'>Account</div></div>"
        "<div class='card-body'>"
        f"<div class='metric-row'><span class='metric-name'>Username</span><span class='metric-value'>{os.getenv('NMS_AUTH_USER', 'admin')}</span></div>"
        "<div class='metric-row'><span class='metric-name'>Password</span><span class='metric-value'>" + masked + "</span></div>"
        "<form hx-post='/settings/password' hx-target='#main-content' hx-swap='innerHTML' style='margin-top:8px'>"
        "<div class='field'><label>New password</label><input type='password' name='password' minlength='8' required></div>"
        "<button type='submit' class='primary'>Change password</button>"
        "</form>"
        "<form hx-post='/settings/password' hx-target='#main-content' hx-swap='innerHTML' style='margin-top:8px'>"
        "<input type='hidden' name='clear' value='1'>"
        "<button type='submit' class='danger'>Clear password</button>"
        "</form>"
        "</div></div>"
        "<div class='card'><div class='card-header'><div class='card-title'>Retention</div></div>"
        "<div class='card-body'>"
        "<form hx-post='/settings/retention' hx-target='#main-content' hx-swap='innerHTML'>"
        f"<div class='field'><label>Keep samples for (days)</label><input type='number' name='retention_days' value='{retention}' min='1' max='365' required></div>"
        "<button type='submit' class='primary'>Save retention</button>"
        "</form>"
        "</div></div>"
        "<div class='card'><div class='card-header'><span class='card-title'>Telegram</span></div>"
        "<div class='card-body'>"
        "<form hx-post='/settings/delivery' hx-target='#main-content' hx-swap='innerHTML'>"
        f"<div class='field'><label>Enable Telegram</label><select name='telegram_enabled'>"
        f"<option value='1' {'selected' if delivery.get('telegram_enabled') else ''}>Yes</option>"
        f"<option value='0' {'selected' if not delivery.get('telegram_enabled') else ''}>No</option>"
        "</select></div>"
        f"<div class='field'><label>Bot token</label><input name='telegram_bot_token' value='{delivery.get('telegram_bot_token','')}'></div>"
        f"<div class='field'><label>Chat ID</label><input name='telegram_chat_id' value='{delivery.get('telegram_chat_id','')}'></div>"
        "<button type='submit' class='primary'>Save</button>"
        "<input type='hidden' name='_csrf' value='{{csrf}}'>"
        "</form></div></div>"
        "<div id='test-result'></div>"
        "<div class='card'><div class='card-header'><span class='card-title'>Test</span></div>"
        "<div class='card-body'><button class='primary' hx-post='/settings/test' hx-target='#test-result' hx-swap='innerHTML'>Send test alert</button></div></div>"
        "<div class='card'><div class='card-header'><div class='card-title'>License</div></div><div class='card-body'>"
        f"<div class='metric-row'><span class='metric-name'>Mode</span><span class='metric-value'>{brand.get('license_mode','mit').upper()}</span></div>"
        f"<div class='metric-row'><span class='metric-name'>Commercial features</span><span class='metric-value'>{'Enabled' if brand.get('license_mode') == 'commercial' else 'Disabled'}</span></div>"
        "<a class='button primary' href='/upgrade'>Upgrade</a>"
        "<a class='button' href='/license'>Manage license</a>"
        "</div></div>"
        "</div>"
    )
    return HTMLResponse(_layout("Settings", body))


@app.post("/settings/retention")
async def update_retention(request: Request):
    form = await request.form()
    days = int(form.get("retention_days", 30))
    if days > 30:
        _require_feature("extended_retention")
    store.save_settings(retention_days=days)
    store.cleanup(retention_days=days)
    return HTMLResponse(_post_save_redirect("/settings"))


@app.post("/settings/password")
async def update_password(request: Request):
    form = await request.form()
    if form.get("clear") == "1":
        store.save_settings(web_password_hash=None, web_auth_enabled=0)
    else:
        pw = form.get("password", "")
        h = __import__("hashlib").sha256(pw.encode()).hexdigest()
        store.save_settings(web_password_hash=h, web_auth_enabled=1)
    return HTMLResponse(_post_save_redirect("/settings"))


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
        now_ts = datetime.utcnow().isoformat()
        for a in deduped:
            rule = rule_map.get(a.get("metric_name"))
            cooldown_min = int((rule or {}).get("cooldown_minutes") or 0)
            last_key = f"{a.get('target_name')}:{a.get('metric_name')}"
            if cooldown_min and last_sent.get(last_key):
                try:
                    last = datetime.fromisoformat(last_sent[last_key])
                    if (datetime.utcnow() - last).total_seconds() < cooldown_min * 60:
                        continue
                except Exception:
                    pass
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

    last_sent: dict[str, str] = {}
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
        for attempt in range(int(settings.get("retry_attempts") or 2)):
            backoff = 2 ** attempt
            try:
                resp = httpx.post(url, json=payload_or_json, timeout=float(settings.get("retry_timeout_sec") or 8.0))
                status = resp.status_code
                if resp.status_code < 400:
                    break
                if attempt + 1 < int(settings.get("retry_attempts") or 2):
                    import time as _time
                    _time.sleep(backoff)
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
        f"<button class='danger' hx-delete='/alerts/{r['id']}' hx-confirm='Delete {r['metric_name']} rule?' hx-target='#main-content' hx-swap='innerHTML'>Delete</button>"
        f"</div></div></div>"
        for r in rules
    )
    body = (
        "<div class='page-header'><h2>Alert rules</h2><button class='primary' hx-get='/alerts/new' hx-target='#main-content' hx-swap='innerHTML'>Add rule</button></div>"
        "<div class='grid'>" + (cards or "<div class='empty'>No rules</div>") + "</div>"
    )
    return HTMLResponse(_layout("Alerts", body))


@app.get("/alerts/new")
async def new_alert_form(request: Request):
    _require_feature("alert_escalation")
    body = _alert_rule_form()
    if request.headers.get("hx-request"):
        return HTMLResponse(body)
    return HTMLResponse(_layout("New alert rule", body))


@app.get("/alerts/{rule_id}/edit")
async def edit_alert_form(rule_id: int):
    _require_feature("alert_escalation")
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
        f"<button class='danger' hx-delete='/targets/{t['id']}' hx-confirm='Delete {t['name']}?' hx-target='#main-content' hx-swap='innerHTML'>Delete</button></div></div></div>"
        for t in rows
    )
    body = (
        "<div class='page-header'><h2>Targets</h2><button class='primary' hx-get='/targets/new' hx-target='#main-content' hx-swap='innerHTML'>Add target</button></div>"
        "<div class='grid'>" + (cards or "<div class='empty'>No targets</div>") + "</div>"
    )
    return HTMLResponse(_layout("Targets", body))


@app.get("/targets/new")
async def new_target_form(request: Request):
    body = _target_form()
    if request.headers.get("hx-request"):
        return HTMLResponse(body)
    return HTMLResponse(_layout("New target", body))


@app.get("/targets/{target_id}")
async def target_detail(target_id: int):
    target = store.get_target(target_id)
    if not target:
        return HTMLResponse(_layout("Not found", "<div class='empty'>Not found</div>"), status_code=404)
    latest = {r["metric_name"]: r for r in store.latest_samples() if r.get("target_id") == target_id}
    metric_defs = store.list_metrics_for_target(target_id)

    def fmt_ts(ts):
        if not ts:
            return "never"
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ts

    def probe_state(metric_name):
        sample = latest.get(metric_name)
        if not sample:
            return "no-sample", "No sample"
        if sample.get("error"):
            return "error", sample["error"]
        return "ok", "OK"

    metric_rows = []
    for m in metric_defs:
        name = m.get("name", "")
        state, state_label = probe_state(name)
        state_class = {"ok": "state-ok", "error": "state-error"}.get(state, "state-unknown")
        value = latest[name]["value"] if name in latest else "—"
        last_ts = fmt_ts(latest[name].get("timestamp")) if name in latest else "never"
        unit = m.get("unit") or ""
        interval = m.get("poll_interval_sec", 60)
        metric_id = m["id"]
        metric_rows.append(
            f"<div class='metric-block' id='metric-{metric_id}' data-target='{target_id}'>"
            f"<div class='metric-row'><div><div class='metric-name'>{name}</div><div class='card-meta'>Interval: {interval}s</div></div>"
            f"<div class='metric-state {state_class}'>{state_label}</div></div>"
            f"<div class='metric-row'><div class='metric-name'>Current</div><div class='metric-value'>{value} {unit}</div></div>"
            f"<div class='metric-row'><div class='metric-name'>Last probe</div><div class='metric-value'>{last_ts}</div></div>"
            f"<form hx-post='/targets/{target_id}/metrics/{metric_id}/config' hx-target='#metric-{metric_id}' hx-swap='innerHTML' class='metric-config'>"
            f"<input type='number' name='interval' value='{interval}' min='10' step='10' style='width:80px' required>"
            f"<button type='submit' class='primary' style='padding:6px 10px'>Save</button>"
            f"</form>"
            f"<div class='metric-history'><div class='chart-header'>"
            f"<button class='range-btn' data-range='24h' data-metric='{name}' onclick='_loadMetricHistory(this)'>24h</button>"
            f"<button class='range-btn' data-range='7d' data-metric='{name}' onclick='_loadMetricHistory(this)'>7d</button>"
            f"<button class='range-btn' data-range='30d' data-metric='{name}' onclick='_loadMetricHistory(this)'>30d</button>"
            f"</div>"
            f"<canvas id='history-{metric_id}'></canvas></div>"
            f"</div>"
        )
    metric_html = "".join(metric_rows) or "<div class='empty'>No metrics configured.</div>"

    alert_rules = store.list_alert_rules_for_target(target_id)
    if alert_rules:
        alert_rows = "".join(
            f"<div class='rule-row'><div><div class='rule-name'>{r.get('description') or r.get('metric_name')}</div>"
            f"<div class='card-meta'>{r.get('metric_name')} {r.get('comparison')} {r.get('threshold')}</div></div>"
            f"<div class='rule-status'>{'Enabled' if r.get('enabled') else 'Disabled'}</div></div>"
            for r in alert_rules
        )
        alert_section = f"<div class='card'><div class='card-header'><div class='card-title'>Watched by rules</div></div><div>{alert_rows}</div></div>"
    else:
        alert_section = "<div class='card'><div class='card-header'><div class='card-title'>Watched by rules</div></div><div class='empty'>No alert rules reference this target.</div></div>"

    enabled_label = "Disable" if target.get("enabled") else "Enable"
    body = f"""
      <div class='page-header'><h2>{target.get('name','')}</h2>
        <div class='actions'>
          <form hx-post='/targets/{target_id}/toggle' hx-target='#main-content' hx-swap='innerHTML' style='display:inline'>
            <button type='submit' class='button'>{enabled_label}</button>
            <input type='hidden' name='enabled' value='{0 if target.get('enabled') else 1}'>
          </form>
          <a class='button' href='/targets/{target_id}/edit'>Edit target</a>
          <button class='danger' hx-delete='/targets/{target_id}' hx-confirm='Delete {target.get('name','')}?' hx-target='#main-content' hx-swap='innerHTML'>Delete</button>
          <button hx-get='/targets' hx-target='#main-content' hx-swap='innerHTML'>Back</button>
        </div>
      </div>
      <div class='grid'>
        <div class='card'>
          <div class='card-header'><div><div class='card-title'>{target.get('kind','').upper()} target</div><div class='card-meta'>{target.get('address','')}</div></div><div class='tier-badge tier-{target.get('tier','T2').lower()}'>{target.get('tier','T2')}</div></div>
          <div class='card-header'><div class='card-title'>Probe status</div></div>
          <div class='probe-status'><div class='state-dot state-{"ok" if any(probe_state(m.get("name",""))[0]=="ok" for m in metric_defs) else "error"}'></div><div class='card-meta'>{fmt_ts(latest[next(iter(latest))].get("timestamp")) if latest else "No samples"}</div></div>
        </div>
        <div class='card'>
          <div class='card-header'><div class='card-title'>Metrics</div></div>
          <div id='metric-list'>{metric_html}</div>
        </div>
        {alert_section}
      </div>
    """
    return HTMLResponse(_layout(target.get("name",""), body))


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


@app.post("/targets/{target_id}/metrics/{metric_id}/config")
async def update_metric_config(target_id: int, metric_id: int, request: Request):
    form = await request.form()
    interval = int(form.get("interval", 60))
    store.update_metric(metric_id, poll_interval_sec=interval)
    target = store.get_target(target_id)
    metric = next((m for m in store.list_metrics_for_target(target_id) if m["id"] == metric_id), None)
    if not target or not metric:
        return HTMLResponse("<div class='empty'>Not found</div>", status_code=404)
    latest = {r["metric_name"]: r for r in store.latest_samples() if r.get("target_id") == target_id}
    sample = latest.get(metric.get("name", ""))
    state = "no-sample"
    state_label = "No sample"
    if sample:
        if sample.get("error"):
            state = "error"
            state_label = sample["error"]
        else:
            state = "ok"
            state_label = "OK"
    unit = metric.get("unit") or ""
    value = sample["value"] if sample else "—"
    from datetime import datetime

    def fmt_ts(ts):
        if not ts:
            return "never"
        try:
            return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ts

    last_ts = fmt_ts(sample.get("timestamp")) if sample else "never"
    return HTMLResponse(
        f"<div class='metric-block'>"
        f"<div class='metric-row'><div><div class='metric-name'>{metric.get('name','')}</div><div class='card-meta'>Interval: {interval}s</div></div>"
        f"<div class='metric-state state-{state}'>{state_label}</div></div>"
        f"<div class='metric-row'><div class='metric-name'>Current</div><div class='metric-value'>{value} {unit}</div></div>"
        f"<div class='metric-row'><div class='metric-name'>Last probe</div><div class='metric-value'>{last_ts}</div></div>"
        f"<form hx-post='/targets/{target_id}/metrics/{metric_id}/config' hx-target='#metric-{metric_id}' hx-swap='innerHTML' class='metric-config'>"
        f"<input type='number' name='interval' value='{interval}' min='10' step='10' style='width:80px' required>"
        f"<button type='submit' class='primary' style='padding:6px 10px'>Save</button>"
        f"</form>"
        f"</div>"
    )


@app.get("/targets/{target_id}/metrics/{metric_name}/history")
async def metric_history(target_id: int, metric_name: str, range: str = "24h"):
    series = store.metric_history(target_id, metric_name, range)
    return {"target_id": target_id, "metric": metric_name, "range": range, "series": series}


@app.post("/targets/{target_id}/toggle")
async def toggle_target(target_id: int, request: Request):
    form = await request.form()
    enabled = form.get("enabled", "0") == "1"
    store.set_target_enabled(target_id, enabled)
    target = store.get_target(target_id)
    if not target:
        return HTMLResponse("<div class='empty'>Not found</div>", status_code=404)
    return HTMLResponse(_post_save_redirect(f"/targets/{target_id}"))


def _post_save_redirect(location: str) -> str:
    return f"<div hx-redirect='{location}'></div>"


def _validate_license_key(key: str) -> bool:
    key = (key or "").strip()
    if not key:
        return False
    # Simple shared-secret format for initial release; will evolve to signed tokens in M3.
    return key.startswith("NMS-NOVA-") and len(key) >= 16


def _load_license() -> nms_license.License:
    brand = store.get_branding_settings()
    mode = brand.get("license_mode", "mit")
    features = set(nms_license.COMMERCIAL_FEATURES) if mode == "commercial" else set(nms_license.MIT_FEATURES)
    return nms_license.License(mode=mode, key=None, features=features)


def _license_active(lic: nms_license.License) -> bool:
    if lic.mode != "commercial":
        return False
    settings = store.get_settings()
    end = settings.get("license_trial_end")
    if end:
        try:
            from datetime import datetime, timezone
            if datetime.now(timezone.utc) > datetime.fromisoformat(end):
                return False
        except Exception:
            pass
    return True


def _upgrade_banner(license_mode: str = "mit") -> str:
    if license_mode != "commercial":
        return """<div class="upgrade-banner"><strong>NMS-Nova Commercial</strong> unlocks extended retention, SNMP, escalation, white-label, RBAC, and more. <a href="/upgrade">Learn more</a>.</div>"""
    return ""


def _layout(title: str, body: str) -> str:
    import secrets
    csrf = secrets.token_urlsafe(16)
    _brand = store.get_branding_settings()
    _brand_title = _brand.get("brand_title") or "NMS-Nova"
    _brand_css = _brand.get("brand_css_url")
    _page_title = f"{_brand_title} - {title}"
    _head = f"""<link rel='stylesheet' href='{_brand_css}' />""" if _brand_css else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>{_page_title}</title>
  {_head}
  <script src='https://unpkg.com/htmx.org@2.0.0'></script>
  <script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js'></script>
  <script src='/static/detail.js'></script>
  <link rel='stylesheet' href='/static/nova.css' />
</head>
<body>
  <header>
    <div class='topbar'>
      <a class='brand' href='/'><span class='brand-dot'></span>{_brand_title}</a>
      <button class='nav-toggle' id='nav-toggle' aria-expanded='false' aria-controls='main-nav'>Menu</button>
    </div>
    <nav id='main-nav'>
      <a href='/'>Dashboard</a>
      <a href='/targets'>Targets</a>
      <a href='/alerts'>Alerts</a>
      <a href='/settings'>Settings</a>
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
    con = sqlite3.connect(store.db_path)
    con.row_factory = sqlite3.Row
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
    _require_feature("multichannel_delivery")
    _require_feature("multichannel_delivery")
    settings = store.get_delivery_settings()
    return JSONResponse({
        "telegram_enabled": bool(settings.get("telegram_enabled")),
        "webhook_enabled": bool(settings.get("webhook_enabled")),
        "webhook_url": settings.get("webhook_url", ""),
        "retry_attempts": int(settings.get("retry_attempts") or 2),
        "retry_timeout_sec": float(settings.get("retry_timeout_sec") or 8.0),
    })


@api_router.get("/alerts/delivery/log")
def api_delivery_log(limit: int = 100):
    _require_feature("multichannel_delivery")
    _require_feature("multichannel_delivery")
    rows = store.recent_delivery_log(limit)
    return JSONResponse([dict(r) for r in rows])


@api_router.post("/alerts/escalate")
def api_execute_escalations(request: Request):
    _require_feature("alert_escalation")
    _require_feature("alert_escalation")
    scopes = getattr(request.state, "api_scopes", [])
    if "admin" not in scopes and not _basic_auth(request) and not _bearer_auth(request):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    rows = store.pending_escalations()
    results = []
    for row in rows:
        if row.get("escalation_target"):
            payload = {
                "rule_id": row["id"],
                "target_name": row.get("target_name"),
                "metric_name": row.get("metric_name"),
                "description": row.get("description"),
                "escalation_target": row.get("escalation_target"),
                "last_alerted_at": row.get("last_alerted_at"),
            }
            results.append({"rule_id": row["id"], "status": "queued", "payload": payload})
    return JSONResponse({"executed": len(results), "items": results})


@api_router.get("/alerts/pending-escalations")
def api_pending_escalations():
    _require_feature("alert_escalation")
    _require_feature("alert_escalation")
    rows = store.pending_escalations()
    return JSONResponse([dict(r) for r in rows])


@api_router.get("/admin/tokens")
def api_list_tokens(request: Request):
    _require_feature("commercial_license")
    scopes = getattr(request.state, "api_scopes", [])
    if "admin" not in scopes and not _basic_auth(request) and not _bearer_auth(request):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    rows = store.list_api_tokens()
    return JSONResponse([dict(r) for r in rows])


@api_router.delete("/admin/tokens/{token_id}")
def api_revoke_token(request: Request, token_id: int):
    _require_feature("commercial_license")
    scopes = getattr(request.state, "api_scopes", [])
    if "admin" not in scopes and not _basic_auth(request) and not _bearer_auth(request):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    store.revoke_api_token(token_id)
    return JSONResponse({"status": "revoked"})


@api_router.post("/admin/tokens")
def api_create_token(request: Request, token: str = "", scope: str = "read"):
    _require_feature("commercial_license")
    scopes = getattr(request.state, "api_scopes", [])
    if "admin" not in scopes and not _basic_auth(request) and not _bearer_auth(request):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    token_id = store.create_api_token(token=token or __import__("secrets").token_urlsafe(32), scope=scope)
    return JSONResponse({"id": token_id, "token": token or __import__("secrets").token_urlsafe(32), "scope": scope})



@api_router.get("/branding")
def api_get_branding():
    _require_feature("white_label")
    settings = store.get_branding_settings()
    return JSONResponse({
        "product_name": settings.get("product_name", "NMS-Nova"),
        "brand_title": settings.get("brand_title", "NMS-Nova"),
        "brand_css_url": settings.get("brand_css_url"),
        "hide_powered_by": bool(settings.get("hide_powered_by")),
        "license_mode": settings.get("license_mode", "mit"),
    })


@api_router.post("/branding")
def api_save_branding(request: Request, body: dict = {}):
    _require_feature("white_label")
    scopes = getattr(request.state, "api_scopes", [])
    if "admin" not in scopes and not _basic_auth(request) and not _bearer_auth(request):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    store.save_branding_settings(body)
    return JSONResponse({"status": "ok"})



@app.get("/settings/branding")
async def branding_form():
    settings = store.get_branding_settings()
    banner = _upgrade_banner(settings.get("license_mode", "mit"))
    body = f"""
    {banner}
    <div class='page-header'><h2>Branding</h2></div>
    <form id='branding-form' hx-post='/settings/branding' hx-target='#main-content' hx-swap='innerHTML'>
      <div id='brand-preview'></div>
      <script src='/static/branding-preview.js'></script>
      <div class='field'><label>Product name</label><input name='product_name' value='{settings.get('product_name','NMS-Nova')}'></div>
      <div class='field'><label>Brand title</label><input name='brand_title' value='{settings.get('brand_title','NMS-Nova')}'></div>
      <div class='field'><label>Custom CSS URL</label><input name='brand_css_url' value='{settings.get('brand_css_url') or ''}' placeholder='https://example.com/brand.css'></div>
      <div class='field'><label>License mode</label><select name='license_mode' {'disabled' if not nms_license.is_enabled(_load_license(), 'commercial_license') else ''}>
        <option value='mit' {'selected' if settings.get('license_mode')=='mit' else ''}>MIT</option>
        <option value='commercial' {'selected' if settings.get('license_mode')=='commercial' else ''}>Commercial</option>
      </select></div>
      <div class='field'><label><input type='checkbox' name='hide_powered_by' {'checked' if settings.get('hide_powered_by') else ''} {'disabled' if not nms_license.is_enabled(_load_license(), 'white_label') else ''}> Hide powered-by line</label></div>
      <input type='hidden' name='_csrf' value='{{csrf}}'>
      <button type='submit'>Save branding</button>
    </form>
    """
    return HTMLResponse(_layout("Branding", body))


@app.post("/settings/branding")
async def save_branding(request: Request):
    form = await request.form()
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    payload = {
        "product_name": form.get("product_name", "NMS-Nova"),
        "brand_title": form.get("brand_title", "NMS-Nova"),
        "brand_css_url": form.get("brand_css_url") or None,
        "hide_powered_by": form.get("hide_powered_by") == "on",
        "license_mode": form.get("license_mode", "mit"),
    }
    if payload["license_mode"] == "commercial":
        _require_feature("commercial_license")
    store.save_branding_settings(payload)
    return HTMLResponse(_post_save_redirect("/settings/branding"))



@app.post("/settings/branding/preview")
async def preview_branding(request: Request):
    form = await request.form()
    preview_brand = {
        "product_name": form.get("product_name", "NMS-Nova"),
        "brand_title": form.get("brand_title", "NMS-Nova"),
        "brand_css_url": form.get("brand_css_url") or None,
        "hide_powered_by": form.get("hide_powered_by") == "on",
        "license_mode": form.get("license_mode", "mit"),
    }
    html = f"""
    <div class='preview-frame'>
      <div class='preview-bar'>{preview_brand['brand_title']}</div>
      <div class='preview-meta'>Preview — {'Commercial' if preview_brand['license_mode']=='commercial' else 'MIT'} license {' | powered by NMS-Nova' if not preview_brand['hide_powered_by'] else ''}</div>
    </div>
    """
    return HTMLResponse(html)





# M15+: commercial license feature gates
# _load_license() already defined above with settings-table source of truth

@app.get("/license")
async def license_page():
    lic = _load_license()
    status = "active" if lic.mode == "commercial" else "inactive"
    body = f"""
    <div class='page-header'><h2>License</h2></div>
    <div class='empty'>
      <p>Current mode: <strong>{lic.mode.upper()}</strong></p>
      <p>Status: <strong>{status}</strong></p>
    </div>
    <form hx-post='/license/activate' hx-target='#main-content' hx-swap='innerHTML'>
      <div class='field'><label>License key</label><input name='license_key' placeholder='Paste commercial license key'></div>
      <input type='hidden' name='_csrf' value='{{csrf}}'>
      <button type='submit' class='primary'>Activate</button>
    </form>
    <form hx-post='/license/deactivate' hx-target='#main-content' hx-swap='innerHTML' style='margin-top:12px'>
      <input type='hidden' name='_csrf' value='{{csrf}}'>
      <button type='submit' class='danger'>Deactivate license</button>
    </form>
    """
    return HTMLResponse(_layout("License", body))


@app.post("/license/activate")
async def activate_license(request: Request):
    form = await request.form()
    key = (form.get("license_key") or "").strip()
    if not key:
        return HTMLResponse("<div class='empty'>License key is required.</div>", status_code=400)
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    valid = _validate_license_key(key)
    if not valid:
        return HTMLResponse("<div class='empty'>Invalid license key.</div>", status_code=400)
    store.save_branding_settings({"license_mode": "commercial"})
    store.save_settings(license_mode="commercial", license_key=key)
    body = """
    <div class='empty'>
      <p>License activated.</p>
      <p><a href='/settings'>Back to Settings</a></p>
    </div>
    """
    return HTMLResponse(_layout("License activated", body))


@app.get("/license")
async def license_page():
    lic = _load_license()
    active = lic.mode == "commercial" and _license_active(lic)
    status = "active" if active else ("trial" if getattr(lic, "trial", False) else "inactive")
    rows = "".join([
        f"<tr><td>{f['name']}</td><td>{'✅' if active else '❌'}</td></tr>"
        for f in nms_license.commercial_features_summary(lic)
    ])
    body = f"""
    <div class='page-header'><h2>License</h2></div>
    <div class='empty'>
      <p>Current mode: <strong>{lic.mode.upper()}</strong></p>
      <p>Status: <strong>{status}</strong></p>
    </div>
    <h3>Commercial feature matrix</h3>
    <table class='table'>
      <thead><tr><th>Feature</th><th>Enabled</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <form hx-post='/license/activate' hx-target='#main-content' hx-swap='innerHTML' style='margin-top:16px'>
      <div class='field'><label>License key</label><input name='license_key' placeholder='Paste commercial license key'></div>
      <input type='hidden' name='_csrf' value='{{csrf}}'>
      <button type='submit' class='primary'>Activate</button>
    </form>
    <form hx-post='/license/trial' hx-target='#main-content' hx-swap='innerHTML' style='margin-top:12px'>
      <input type='hidden' name='_csrf' value='{{csrf}}'>
      <button type='submit' class='button'>Start 14-day trial</button>
    </form>
    <form hx-post='/license/deactivate' hx-target='#main-content' hx-swap='innerHTML' style='margin-top:12px'>
      <input type='hidden' name='_csrf' value='{{csrf}}'>
      <button type='submit' class='danger'>Deactivate license</button>
    </form>
    """
    return HTMLResponse(_layout("License", body))


@app.post("/license/activate")
async def activate_license(request: Request):
    form = await request.form()
    key = (form.get("license_key") or "").strip()
    if not key:
        return HTMLResponse("<div class='empty'>License key is required.</div>", status_code=400)
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    valid = _validate_license_key(key)
    if not valid:
        return HTMLResponse("<div class='empty'>Invalid license key.</div>", status_code=400)
    store.save_branding_settings({"license_mode": "commercial"})
    store.save_settings(license_mode="commercial", license_key=key)
    body = """
    <div class='empty'>
      <p>License activated.</p>
      <p><a href='/settings'>Back to Settings</a></p>
    </div>
    """
    return HTMLResponse(_layout("License activated", body))


@app.post("/license/deactivate")
async def deactivate_license(request: Request):
    form = await request.form()
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    store.save_branding_settings({"license_mode": "mit"})
    store.save_settings(license_mode="mit", license_key=None, license_trial_start=None, license_trial_end=None)
    body = """
    <div class='empty'>
      <p>License deactivated. Reverted to MIT mode.</p>
      <p><a href='/settings'>Back to Settings</a></p>
    </div>
    """
    return HTMLResponse(_layout("License deactivated", body))


@app.post("/license/trial")
async def start_trial(request: Request):
    form = await request.form()
    if form.get("_csrf") != request.cookies.get("_csrf"):
        return HTMLResponse("<div class='empty'>Invalid session token.</div>", status_code=403)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=14)
    store.save_branding_settings({"license_mode": "commercial"})
    store.save_settings(
        license_mode="commercial",
        license_key=None,
        license_trial_start=now.isoformat(),
        license_trial_end=end.isoformat(),
    )
    body = f"""
    <div class='empty'>
      <p>Trial started. Expires on {end.strftime('%Y-%m-%d')}.</p>
      <p><a href='/settings'>Back to Settings</a></p>
    </div>
    """
    return HTMLResponse(_layout("Trial started", body))


@app.get("/license/check")
def license_check():
    lic = _load_license()
    active = lic.mode == "commercial" and _license_active(lic)
    trial = getattr(lic, "trial", False)
    features = nms_license.commercial_features_summary(lic)
    return JSONResponse({
        "mode": lic.mode,
        "commercial_features_enabled": active,
        "trial": trial,
        "features": features,
        "support_contact": "sales@packet-loss.net" if lic.mode == "commercial" else None,
    })


@app.get("/upgrade")
async def upgrade_page():
    lic = _load_license()
    active = lic.mode == "commercial" and _license_active(lic)
    rows = "".join([
        f"<tr><td>{f['name']}</td><td>{'✅' if active else '❌'}</td></tr>"
        for f in nms_license.commercial_features_summary(lic)
    ])
    body = f"""
    <div class='page-header'><h2>Commercial License</h2></div>
    <div class='empty'>
      <p>NMS-Nova commercial license removes usage restrictions and includes priority support.</p>
      <p>Contact <a href='mailto:sales@packet-loss.net'>sales@packet-loss.net</a> for pricing.</p>
    </div>
    <h3>Feature matrix</h3>
    <table class='table'>
      <thead><tr><th>Feature</th><th>Enabled</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """
    return HTMLResponse(_layout("Upgrade", body))

app.include_router(api_router)


# Planned commercial-only route stubs
@app.get("/settings/rbac")
async def rbac_form():
    _require_feature("rbac")
    return HTMLResponse("<div class='empty'>RBAC is a commercial feature.</div>")

@app.post("/settings/rbac")
async def rbac_save():
    _require_feature("rbac")
    return HTMLResponse(_post_save_redirect("/settings/rbac"))

@app.get("/settings/backup")
async def backup_form():
    _require_feature("backup_restore")
    return HTMLResponse("<div class='empty'>Backup/restore is a commercial feature.</div>")

@app.post("/settings/backup")
async def backup_run():
    _require_feature("backup_restore")
    return HTMLResponse(_post_save_redirect("/settings/backup"))

@app.get("/dashboards")
async def custom_dashboards():
    _require_feature("custom_dashboards")
    return HTMLResponse("<div class='empty'>Custom dashboards are a commercial feature.</div>")
