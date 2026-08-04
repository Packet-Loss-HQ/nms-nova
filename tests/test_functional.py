"""Functional tests for NMS-Nova."""
import os
import urllib.request
import urllib.parse
import urllib.error
import sqlite3

BASE = os.environ.get("NMS_BASE_URL", "http://127.0.0.1:8001")
AUTH = os.environ.get("NMS_BASIC_AUTH", "")


def _auth_headers():
    return {"Authorization": AUTH} if AUTH else {}


def request(path, data=None):
    req = urllib.request.Request(
        BASE + path,
        data=urllib.parse.urlencode(data).encode() if data else None,
        headers=_auth_headers(),
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def test_health():
    req = urllib.request.Request(BASE + "/health", headers={})
    with urllib.request.urlopen(req) as r:
        assert r.status == 200


def test_setup_page():
    status, _ = request("/setup")
    assert status == 200


def test_dashboard_or_empty_state():
    status, body = request("/")
    assert status == 200
    assert "NMS-Nova" in body or "Setup" in body or "targets" in body


def test_chart_endpoints():
    for rng in ("24h", "7d", "30d"):
        status, body = request(f"/chart/does-not-matter?range={rng}")
        assert status in (200, 404)


def test_db_created():
    status, body = request("/health")
    assert status == 200
    import json
    data = json.loads(body)
    assert "db" in data
    assert "sample_count" in data["db"]
    assert "target_count" in data["db"]


def test_settings_page():
    if not AUTH:
        return
    status, _ = request("/settings")
    assert status == 200


def test_settings_round_trip():
    if not AUTH:
        return
    status, _ = request("/settings/retention", {"retention_days": "7"})
    assert status == 200
    status, _ = request("/settings/password", {"password": "Monkey1234!"})
    assert status == 200
    status, _ = request("/settings/password", {"clear": "1"})
    assert status == 200


def test_target_toggle():
    if not AUTH:
        return
    status, _ = request("/targets/1/toggle", {"enabled": "0"})
    assert status == 200
    status, _ = request("/targets/1/toggle", {"enabled": "1"})
    assert status == 200
