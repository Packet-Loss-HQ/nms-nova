"""Functional tests for NMS-Nova."""
import urllib.request
import urllib.parse
import urllib.error
import sqlite3
import os

BASE = os.environ.get("NMS_BASE_URL", "http://127.0.0.1:8000")
AUTH = os.environ.get("NMS_BASIC_AUTH", "")  # set NMS_BASIC_AUTH=admin:admin for local runs


def request(path, data=None):
    req = urllib.request.Request(
        BASE + path,
        data=urllib.parse.urlencode(data).encode() if data else None,
        headers={"Authorization": AUTH},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def test_dashboard_renders():
    status, _ = request("/")
    assert status == 200


def test_targets_empty_state():
    status, body = request("/targets")
    assert status == 200
    assert "No targets" in body


def test_setup_page():
    status, _ = request("/setup")
    assert status == 200


def test_settings_page():
    status, _ = request("/settings")
    assert status == 200


def test_chart_endpoints():
    for rng in ("24h", "7d", "30d"):
        status, body = request(f"/chart/does-not-matter?range={rng}")
        assert status in (200, 404)


def test_public_health():
    req = urllib.request.Request(BASE + "/health", headers={})
    with urllib.request.urlopen(req) as r:
        assert r.status == 200


def test_auth_challenge():
    req = urllib.request.Request(BASE + "/", headers={})
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        assert e.code == 401


def test_settings_round_trip():
    status, _ = request("/settings/retention", {"retention_days": "7"})
    assert status == 200
    status, _ = request("/settings/password", {"password": "Monkey1234!"})
    assert status == 200
    status, _ = request("/settings/password", {"clear": "1"})
    assert status == 200


def test_db_exists():
    db_path = os.environ.get("NMS_DB", "/opt/nms-nova/state/nms-nova.db")
    assert os.path.exists(db_path), f"missing {db_path}"


def test_target_toggle():
    status, _ = request("/targets/1/toggle", {"enabled": "0"})
    assert status == 200
    status, _ = request("/targets/1/toggle", {"enabled": "1"})
    assert status == 200

# NOTE: pytest must be installed separately if running outside CI.
