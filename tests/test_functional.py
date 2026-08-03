"""Functional tests for NMS-Nova."""
import urllib.request
import urllib.parse
import urllib.error
import sqlite3
import os

BASE = os.environ.get("NMS_BASE_URL", "http://127.0.0.1:8000")
AUTH = os.environ.get("NMS_BASIC_AUTH", "")  # set NMS_BASIC_AUTH=admin:admin for local runs
DB_PATH = os.environ.get("NMS_DB", "/tmp/nms-nova-test.db")


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


def test_db_created():
    assert os.path.exists(DB_PATH), f"missing {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {r[0] for r in rows}
        assert "targets" in table_names
        assert "samples" in table_names
    finally:
        conn.close()


def test_chart_endpoints():
    for rng in ("24h", "7d", "30d"):
        status, body = request(f"/chart/does-not-matter?range={rng}")
        assert status in (200, 404)


# NOTE: pytest must be installed separately if running outside CI.
