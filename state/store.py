#!/usr/bin/env python3
"""
import hashlib
NMS-Nova state store with SQLite + WAL.
Append-only metric_samples with daily rollover cleanup.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


class MetricsStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init()

    def _init(self) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL,
                    address TEXT NOT NULL,
                    probe_type TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'T2',
                    ssh_key TEXT,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_definitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    unit TEXT,
                    poll_interval_sec INTEGER NOT NULL DEFAULT 60,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    params TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(target_id) REFERENCES targets(id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    definition_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    value REAL NOT NULL,
                    FOREIGN KEY(target_id) REFERENCES targets(id),
                    FOREIGN KEY(definition_id) REFERENCES metric_definitions(id)
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_metric_samples_ts_target_def ON metric_samples(timestamp, target_id, definition_id)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS metric_samples_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, target_id INTEGER NOT NULL, definition_id INTEGER NOT NULL, timestamp TIMESTAMP NOT NULL, value REAL NOT NULL, error TEXT, archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_metric_samples_archive_ts_target_def ON metric_samples_archive(timestamp, target_id, definition_id)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_metric_def_target ON metric_definitions(target_id)"
            )
            try:
                con.execute("ALTER TABLE metric_samples ADD COLUMN error TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE metric_definitions ADD COLUMN params TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE targets ADD COLUMN ssh_key TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE targets ADD COLUMN snmp_community TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE targets ADD COLUMN snmp_v3_user TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE targets ADD COLUMN snmp_v3_auth TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE targets ADD COLUMN snmp_v3_priv TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE targets ADD COLUMN snmp_v3_auth_key TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE targets ADD COLUMN snmp_v3_priv_key TEXT")
            except Exception:
                pass
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    scope TEXT NOT NULL DEFAULT "read",
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    comparison TEXT NOT NULL DEFAULT 'gt',
                    consecutive INTEGER NOT NULL DEFAULT 2,
                    description TEXT NOT NULL DEFAULT '',
                    delivery TEXT NOT NULL DEFAULT 'all',
                    cooldown_minutes INTEGER NOT NULL DEFAULT 0,
                    escalation_target TEXT,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT DEFAULT (datetime('now')),
                    destination TEXT,
                    alert_count INTEGER,
                    status INTEGER,
                    error TEXT
                )
                """
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS branding_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    product_name TEXT NOT NULL DEFAULT 'NMS-Nova',
                    brand_title TEXT NOT NULL DEFAULT 'NMS-Nova',
                    brand_css_url TEXT,
                    hide_powered_by BOOLEAN NOT NULL DEFAULT 0,
                    license_mode TEXT NOT NULL DEFAULT 'mit'
                )
                """
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    telegram_enabled BOOLEAN NOT NULL DEFAULT 0,
                    telegram_bot_token TEXT NOT NULL DEFAULT '',
                    telegram_chat_id TEXT NOT NULL DEFAULT '',
                    webhook_enabled BOOLEAN NOT NULL DEFAULT 0,
                    webhook_url TEXT,
                    retry_attempts INTEGER NOT NULL DEFAULT 2,
                    retry_timeout_sec REAL NOT NULL DEFAULT 8.0
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    retention_days INTEGER NOT NULL DEFAULT 30,
                    web_password_hash TEXT,
                    web_auth_enabled BOOLEAN NOT NULL DEFAULT 0,
                    license_mode TEXT NOT NULL DEFAULT 'mit',
                    license_key TEXT,
                    license_trial_start TEXT,
                    license_trial_end TEXT
                )
                """
            )
            # Migration for existing DBs
            try:
                con.execute("ALTER TABLE settings ADD COLUMN license_mode TEXT NOT NULL DEFAULT 'mit'")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE settings ADD COLUMN license_key TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE settings ADD COLUMN license_trial_start TEXT")
            except Exception:
                pass
            try:
                con.execute("ALTER TABLE settings ADD COLUMN license_trial_end TEXT")
            except Exception:
                pass
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'viewer',
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_dashboards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    target_filter TEXT NOT NULL DEFAULT 'all',
                    layout TEXT NOT NULL DEFAULT 'grid',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_widgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dashboard_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL DEFAULT 0,
                    metric_name TEXT NOT NULL,
                    chart_type TEXT NOT NULL DEFAULT 'line',
                    range TEXT NOT NULL DEFAULT '24h',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(dashboard_id) REFERENCES custom_dashboards(id) ON DELETE CASCADE
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_dashboards_sort ON custom_dashboards(sort_order)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_widgets_dashboard ON dashboard_widgets(dashboard_id, sort_order)")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_baselines (
                    target_id INTEGER NOT NULL,
                    definition_id INTEGER NOT NULL,
                    mean REAL NOT NULL DEFAULT 0,
                    stddev REAL NOT NULL DEFAULT 0,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(target_id, definition_id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL,
                    definition_id INTEGER NOT NULL,
                    value REAL NOT NULL,
                    zscore REAL NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'warning',
                    detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_anomalies_detected ON metric_anomalies(detected_at)")
            con.commit()
        finally:
            con.close()

    # User management
    def list_users(self) -> list[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT id, username, role, enabled, created_at FROM users ORDER BY username").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def get_user(self, username: str) -> dict | None:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def create_user(self, username: str, password: str, role: str = "viewer") -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                (username, hashlib.sha256(password.encode()).hexdigest(), role),
            )
            con.commit()
        finally:
            con.close()

    def update_user_role(self, username: str, role: str) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
            con.commit()
        finally:
            con.close()

    def set_user_enabled(self, username: str, enabled: bool) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE users SET enabled = ? WHERE username = ?", (1 if enabled else 0, username))
            con.commit()
        finally:
            con.close()

    def delete_user(self, username: str) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM users WHERE username = ?", (username,))
            con.commit()
        finally:
            con.close()

    def list_dashboards(self) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM custom_dashboards ORDER BY sort_order, id").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def get_dashboard(self, dashboard_id: int) -> Optional[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM custom_dashboards WHERE id = ?", (dashboard_id,)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def create_dashboard(self, name: str, description: str = "", target_filter: str = "all", layout: str = "grid", sort_order: int = 0) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO custom_dashboards(name, description, target_filter, layout, sort_order) VALUES(?,?,?,?,?)",
                (name, description, target_filter, layout, sort_order),
            )
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def update_dashboard(self, dashboard_id: int, **fields: Any) -> None:
        allowed = {"name", "description", "target_filter", "layout", "sort_order", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [dashboard_id]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"UPDATE custom_dashboards SET {sets} WHERE id=?", vals)
            con.commit()
        finally:
            con.close()

    def delete_dashboard(self, dashboard_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM dashboard_widgets WHERE dashboard_id=?", (dashboard_id,))
            con.execute("DELETE FROM custom_dashboards WHERE id=?", (dashboard_id,))
            con.commit()
        finally:
            con.close()

    def add_widget(self, dashboard_id: int, metric_name: str, chart_type: str = "line", range: str = "24h", sort_order: int = 0, target_id: int = 0) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO dashboard_widgets(dashboard_id, target_id, metric_name, chart_type, range, sort_order) VALUES(?,?,?,?,?,?)",
                (dashboard_id, target_id, metric_name, chart_type, range, sort_order),
            )
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def list_widgets(self, dashboard_id: int) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM dashboard_widgets WHERE dashboard_id=? ORDER BY sort_order, id", (dashboard_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def update_widget(self, widget_id: int, **fields: Any) -> None:
        allowed = {"metric_name", "chart_type", "range", "sort_order", "target_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [widget_id]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"UPDATE dashboard_widgets SET {sets} WHERE id=?", vals)
            con.commit()
        finally:
            con.close()

    def delete_widget(self, widget_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM dashboard_widgets WHERE id=?", (widget_id,))
            con.commit()
        finally:
            con.close()

    def upsert_target(self, name: str, kind: str, address: str, probe_type: str, tier: str = "T2") -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute("SELECT id FROM targets WHERE name = ?", (name,))
            row = cur.fetchone()
            if row:
                target_id = row[0]
                con.execute(
                    "UPDATE targets SET kind=?, address=?, probe_type=?, tier=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (kind, address, probe_type, tier, target_id),
                )
            else:
                cur = con.execute(
                    "INSERT INTO targets(name, kind, address, probe_type, tier) VALUES(?,?,?,?,?)",
                    (name, kind, address, probe_type, tier),
                )
                target_id = cur.lastrowid
            con.commit()
            return target_id
        finally:
            con.close()

    def add_metric_definition(self, target_id: int, name: str, unit: Optional[str], poll_interval_sec: int, enabled: bool = True, params: Optional[dict] = None) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO metric_definitions(target_id, name, unit, poll_interval_sec, enabled, params) VALUES(?,?,?,?,?,?)",
                (target_id, name, unit, int(poll_interval_sec), 1 if enabled else 0, json.dumps(params) if params else None),
            )
            definition_id = cur.lastrowid
            con.commit()
            return definition_id
        finally:
            con.close()

    def insert_sample(self, target_id: int, definition_id: int, value: float, error: Optional[str] = None) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO metric_samples(target_id, definition_id, value, error) VALUES(?,?,?,?)",
                (target_id, definition_id, value, error),
            )
            con.commit()
        finally:
            con.close()

    def latest_samples(self) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """
                SELECT s.id, s.target_id, s.definition_id, s.timestamp, s.value, s.error, d.name AS metric_name, t.name AS target_name
                FROM metric_samples s
                JOIN metric_definitions d ON d.id = s.definition_id
                JOIN targets t ON t.id = s.target_id
                WHERE s.id IN (
                    SELECT MAX(id) FROM metric_samples GROUP BY target_id, definition_id
                )
                ORDER BY s.target_id, s.definition_id
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def cleanup(self, retention_days: int = 30) -> None:
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                "INSERT INTO metric_samples_archive (target_id, definition_id, timestamp, value, error) SELECT target_id, definition_id, timestamp, value, error FROM metric_samples WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
            con.execute("DELETE FROM metric_samples WHERE timestamp < ?", (cutoff.isoformat(),))
            con.commit()
        finally:
            con.close()

    def archive_stats(self) -> dict:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            total = con.execute("SELECT COUNT(*) FROM metric_samples_archive").fetchone()[0]
            oldest = con.execute("SELECT MIN(timestamp), MAX(timestamp) FROM metric_samples_archive").fetchone()
            return {
                "archive_count": total or 0,
                "archive_oldest": oldest[0] if total else None,
                "archive_newest": oldest[1] if total else None,
            }
        finally:
            con.close()

    def migrate_add_alert_rule_delivery_columns(self) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            existing = {r[1] for r in con.execute("PRAGMA table_info(alert_rules)").fetchall()}
            for col in ("delivery", "cooldown_minutes", "escalation_target", "escalation_after_minutes"):
                if col not in existing:
                    con.execute(f"ALTER TABLE alert_rules ADD COLUMN {col} TEXT")
            con.commit()
        finally:
            con.close()

    def migrate_add_delivery_columns(self) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            existing = {r[1] for r in con.execute("PRAGMA table_info(delivery_settings)").fetchall()}
            for col in ("retry_attempts INTEGER NOT NULL DEFAULT 2", "retry_timeout_sec REAL NOT NULL DEFAULT 8.0"):
                name, rest = col.split(" ", 1)
                if name not in existing:
                    con.execute(f"ALTER TABLE delivery_settings ADD COLUMN {name} {rest}")
            con.commit()
        finally:
            con.close()

    def list_targets(self) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM targets ORDER BY name").fetchall()]
        finally:
            con.close()

    def get_target(self, target_id: int) -> Optional[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def get_target_by_name(self, name: str) -> Optional[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM targets WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def create_target(self, name: str, kind: str, address: str, probe_type: str, tier: str = "T2", ssh_key: Optional[str] = None) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO targets(name, kind, address, probe_type, tier, ssh_key, enabled) VALUES(?,?,?,?,?,?,1)",
                (name, kind, address, probe_type, tier, ssh_key),
            )
            target_id = cur.lastrowid
            con.commit()
            return target_id
        finally:
            con.close()

    def update_target(self, target_id: int, **fields: Any) -> None:
        allowed = {
            "name",
            "kind",
            "address",
            "probe_type",
            "tier",
            "enabled",
            "snmp_community",
            "snmp_v3_user",
            "snmp_v3_auth",
            "snmp_v3_priv",
            "snmp_v3_auth_key",
            "snmp_v3_priv_key",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [target_id]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"UPDATE targets SET {sets} WHERE id=?", vals)
            con.commit()
        finally:
            con.close()

    def set_target_enabled(self, target_id: int, enabled: bool) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE targets SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (1 if enabled else 0, target_id))
            con.commit()
        finally:
            con.close()

    def probe_reliability(self, target_id: int) -> dict:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            total = con.execute(
                "SELECT count(*) FROM metric_samples WHERE target_id=? AND timestamp >= datetime('now','-24 hours')",
                (target_id,),
            ).fetchone()[0]
            errors = con.execute(
                "SELECT count(*) FROM metric_samples WHERE target_id=? AND timestamp >= datetime('now','-24 hours') AND error IS NOT NULL AND error != ''",
                (target_id,),
            ).fetchone()[0]
            success = max(total - errors, 0)
            rate = (success / total * 100) if total else 100.0
            return {"total": total, "errors": errors, "success_rate": round(rate, 1)}
        finally:
            con.close()

    def get_settings(self) -> dict:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM settings WHERE id=1").fetchone()
            return dict(row) if row else {"retention_days": 30, "web_auth_enabled": 0, "web_password_hash": None, "license_mode": "mit", "license_key": None}
        finally:
            con.close()

    def save_settings(self, **fields: Any) -> None:
        allowed = {"retention_days", "web_password_hash", "web_auth_enabled", "license_mode", "license_key"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [1]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"INSERT OR REPLACE INTO settings(id, {', '.join(updates.keys())}) VALUES(?, {', '.join(['?'] * len(updates))})", [1] + list(updates.values()))
            con.commit()
        finally:
            con.close()

    def delete_target(self, target_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM metric_samples WHERE target_id = ?", (target_id,))
            con.execute("DELETE FROM metric_definitions WHERE target_id = ?", (target_id,))
            con.execute("DELETE FROM targets WHERE id = ?", (target_id,))
            con.commit()
        finally:
            con.close()

    def list_metrics_for_target(self, target_id: int) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM metric_definitions WHERE target_id = ?", (target_id,)).fetchall()]
        finally:
            con.close()

    def create_metric(self, target_id: int, name: str, unit: Optional[str], poll_interval_sec: int, enabled: bool = True) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO metric_definitions(target_id, name, unit, poll_interval_sec, enabled) VALUES(?,?,?,?,?)",
                (target_id, name, unit, int(poll_interval_sec), 1 if enabled else 0),
            )
            definition_id = cur.lastrowid
            con.commit()
            return definition_id
        finally:
            con.close()

    def update_metric(self, definition_id: int, **fields: Any) -> None:
        allowed = {"name", "unit", "poll_interval_sec", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [definition_id]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"UPDATE metric_definitions SET {sets} WHERE id=?", vals)
            con.commit()
        finally:
            con.close()

    def delete_metric(self, definition_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM metric_samples WHERE definition_id = ?", (definition_id,))
            con.execute("DELETE FROM metric_definitions WHERE id = ?", (definition_id,))
            con.commit()
        finally:
            con.close()


    def list_metric_definitions(self, target_id: Optional[int] = None) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            if target_id is None:
                rows = con.execute("SELECT * FROM metric_definitions ORDER BY target_id, name").fetchall()
            else:
                rows = con.execute("SELECT * FROM metric_definitions WHERE target_id = ? ORDER BY name", (target_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def recent_delivery_log(self, limit: int = 100) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM delivery_log ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def list_dashboards(self) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM custom_dashboards ORDER BY sort_order, id").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def get_dashboard(self, dashboard_id: int) -> Optional[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM custom_dashboards WHERE id = ?", (dashboard_id,)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def create_dashboard(self, name: str, description: str = "", target_filter: str = "all", layout: str = "grid", sort_order: int = 0) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO custom_dashboards(name, description, target_filter, layout, sort_order) VALUES(?,?,?,?,?)",
                (name, description, target_filter, layout, sort_order),
            )
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def update_dashboard(self, dashboard_id: int, **fields: Any) -> None:
        allowed = {"name", "description", "target_filter", "layout", "sort_order", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [dashboard_id]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"UPDATE custom_dashboards SET {sets} WHERE id=?", vals)
            con.commit()
        finally:
            con.close()

    def delete_dashboard(self, dashboard_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM dashboard_widgets WHERE dashboard_id=?", (dashboard_id,))
            con.execute("DELETE FROM custom_dashboards WHERE id=?", (dashboard_id,))
            con.commit()
        finally:
            con.close()

    def add_widget(self, dashboard_id: int, metric_name: str, chart_type: str = "line", range: str = "24h", sort_order: int = 0, target_id: int = 0) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO dashboard_widgets(dashboard_id, target_id, metric_name, chart_type, range, sort_order) VALUES(?,?,?,?,?,?)",
                (dashboard_id, target_id, metric_name, chart_type, range, sort_order),
            )
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def list_widgets(self, dashboard_id: int) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT * FROM dashboard_widgets WHERE dashboard_id=? ORDER BY sort_order, id", (dashboard_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def update_widget(self, widget_id: int, **fields: Any) -> None:
        allowed = {"metric_name", "chart_type", "range", "sort_order", "target_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [widget_id]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"UPDATE dashboard_widgets SET {sets} WHERE id=?", vals)
            con.commit()
        finally:
            con.close()

    def delete_widget(self, widget_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM dashboard_widgets WHERE id=?", (widget_id,))
            con.commit()
        finally:
            con.close()

    def get_branding_settings(self) -> dict:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM branding_settings WHERE id = 1").fetchone()
            return dict(row) if row else {
                "product_name": "NMS-Nova",
                "brand_title": "NMS-Nova",
                "brand_css_url": None,
                "hide_powered_by": False,
                "license_mode": "mit",
            }
        finally:
            con.close()

    def save_branding_settings(self, settings: dict) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                """
                INSERT INTO branding_settings(id, product_name, brand_title, brand_css_url, hide_powered_by, license_mode)
                VALUES(1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    product_name=excluded.product_name,
                    brand_title=excluded.brand_title,
                    brand_css_url=excluded.brand_css_url,
                    hide_powered_by=excluded.hide_powered_by,
                    license_mode=excluded.license_mode
                """,
                (
                    settings.get("product_name", "NMS-Nova"),
                    settings.get("brand_title", "NMS-Nova"),
                    settings.get("brand_css_url"),
                    1 if settings.get("hide_powered_by") else 0,
                    settings.get("license_mode", "mit"),
                ),
            )
            con.commit()
        finally:
            con.close()

    def revoke_api_token(self, token_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE api_tokens SET enabled = 0 WHERE id = ?", (token_id,))
            con.commit()
        finally:
            con.close()

    def list_api_tokens(self) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT id, token, scope, enabled FROM api_tokens ORDER BY id").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def create_api_token(self, token: str, scope: str = "read", enabled: bool = True) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute("INSERT INTO api_tokens(token, scope, enabled) VALUES(?,?,?)", (token, scope, 1 if enabled else 0))
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def list_alert_rules(self) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM alert_rules ORDER BY id").fetchall()]
        finally:
            con.close()

    def list_alert_rules_for_target(self, target_id: int) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [
                dict(r) for r in con.execute(
                    "SELECT * FROM alert_rules WHERE metric_name IN (SELECT name FROM metric_definitions WHERE target_id = ?) ORDER BY id",
                    (target_id,),
                ).fetchall()
            ]
        finally:
            con.close()

    def metric_history(self, target_id: int, metric_name: str, range: str = "24h") -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
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
                SELECT {bucket} AS ts, avg(s.value) AS value
                FROM metric_samples s
                JOIN metric_definitions d ON d.id = s.definition_id
                WHERE s.target_id = ? AND d.name = ? AND {where}
                GROUP BY ts
                ORDER BY ts ASC
                """,
                (target_id, metric_name),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def pending_escalations(self, limit: int = 200) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("""
                SELECT ar.id, ar.metric_name, ar.threshold, ar.comparison, ar.consecutive,
                       ar.description, ar.enabled, ar.updated_at, ar.cooldown_minutes,
                       ar.escalation_target, ar.escalation_after_minutes
                FROM alert_rules ar
                WHERE ar.enabled = 1
                  AND ar.escalation_target IS NOT NULL
                  AND ar.escalation_target != ''
                  AND ar.escalation_after_minutes > 0
                ORDER BY ar.id
                LIMIT ?
            """, (int(limit),)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def apply_escalation(self, rule_id: int, target: str) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE alert_rules SET escalation_target = ? WHERE id = ?", (target, int(rule_id)))
            con.commit()
        finally:
            con.close()
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("""
                SELECT ar.id, ar.metric_name, ar.threshold, ar.comparison, ar.consecutive,
                       ar.description, ar.enabled, ar.updated_at, ar.cooldown_minutes,
                       ar.escalation_target, ar.escalation_after_minutes
                FROM alert_rules ar
                WHERE ar.enabled = 1
                  AND ar.escalation_target IS NOT NULL
                  AND ar.escalation_target != ''
                  AND ar.escalation_after_minutes > 0
                ORDER BY ar.id
                LIMIT ?
            """, (int(limit),)).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM alert_rules ORDER BY id").fetchall()]
        finally:
            con.close()

    def create_alert_rule(self, metric_name: str, threshold: float, comparison: str = "gt", consecutive: int = 2, description: str = "", enabled: bool = True) -> int:
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO alert_rules(metric_name, threshold, comparison, consecutive, description, enabled) VALUES(?,?,?,?,?,?)",
                (metric_name, float(threshold), comparison, int(consecutive), description, 1 if enabled else 0),
            )
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def update_alert_rule(self, rule_id: int, **fields: Any) -> None:
        allowed = {"metric_name", "threshold", "comparison", "consecutive", "description", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [rule_id]
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(f"UPDATE alert_rules SET {sets} WHERE id=?", vals)
            con.commit()
        finally:
            con.close()

    def delete_alert_rule(self, rule_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
            con.commit()
        finally:
            con.close()


    def log_delivery(self, destination: str, alert_count: int, status: int, error: str | None = None) -> None:
        con = self._conn()
        try:
            con.execute(
                "INSERT INTO delivery_log(destination, alert_count, status, error) VALUES (?, ?, ?, ?)",
                (destination, alert_count, status, error),
            )
            con.commit()
        except Exception:
            pass
        finally:
            con.close()

    def save_alert_rule(self, rule: dict) -> int:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute("INSERT INTO alert_rules(metric_name, threshold, comparison, consecutive, description, enabled, delivery) VALUES (?, ?, ?, ?, ?, ?, ?)", (
                rule.get("metric_name"), rule.get("threshold"), rule.get("comparison", "gt"), rule.get("consecutive", 2), rule.get("description", ""), 1 if rule.get("enabled", True) else 0, rule.get("delivery", "all"),
            ))
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def update_alert_rule(self, rule_id: int, rule: dict) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE alert_rules SET metric_name=?, threshold=?, comparison=?, consecutive=?, description=?, enabled=?, delivery=? WHERE id=?", (
                rule.get("metric_name"), rule.get("threshold"), rule.get("comparison", "gt"), rule.get("consecutive", 2), rule.get("description", ""), 1 if rule.get("enabled", True) else 0, rule.get("delivery", "all"), rule_id,
            ))
            con.commit()
        except Exception:
            pass
        finally:
            con.close()

    def log_delivery(self, destination: str, alert_count: int, status: int, error: str | None = None) -> None:
        con = self._conn()
        try:
            con.execute("INSERT INTO delivery_log(destination, alert_count, status, error) VALUES (?, ?, ?, ?)", (destination, alert_count, status, error))
            con.commit()
        except Exception:
            pass
        finally:
            con.close()

    def get_delivery_settings(self) -> dict:
            con = sqlite3.connect(self.db_path)
            con.row_factory = sqlite3.Row
            try:
                row = con.execute("SELECT * FROM delivery_settings WHERE id = 1").fetchone()
                return dict(row) if row else {
                    "id": 1,
                    "telegram_enabled": False,
                    "telegram_bot_token": "",
                    "telegram_chat_id": "",
                    "webhook_enabled": False,
                    "webhook_url": "",
                }
            finally:
                con.close()

    def save_delivery_settings(self, settings: dict) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                """INSERT INTO delivery_settings(id, telegram_enabled, telegram_bot_token, telegram_chat_id, webhook_enabled, webhook_url)
                   VALUES(1, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       telegram_enabled=excluded.telegram_enabled,
                       telegram_bot_token=excluded.telegram_bot_token,
                       telegram_chat_id=excluded.telegram_chat_id,
                       webhook_enabled=excluded.webhook_enabled,
                       webhook_url=excluded.webhook_url""",
                (
                    1 if settings.get("telegram_enabled") else 0,
                    settings.get("telegram_bot_token", ""),
                    settings.get("telegram_chat_id", ""),
                    1 if settings.get("webhook_enabled") else 0,
                    settings.get("webhook_url", ""),
                ),
            )
            con.commit()
        finally:
            con.close()

    def get_baseline(self, target_id: int, definition_id: int) -> dict | None:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM metric_baselines WHERE target_id=? AND definition_id=?", (target_id, definition_id)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def upsert_baseline(self, target_id: int, definition_id: int, mean: float, stddev: float, sample_count: int) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "INSERT INTO metric_baselines(target_id, definition_id, mean, stddev, sample_count, updated_at) VALUES(?,?,?,?,?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(target_id, definition_id) DO UPDATE SET mean=excluded.mean, stddev=excluded.stddev, sample_count=excluded.sample_count, updated_at=excluded.updated_at",
                (target_id, definition_id, float(mean), float(stddev), int(sample_count)),
            )
            con.commit()
        finally:
            con.close()

    def list_anomalies(self, limit: int = 100) -> List[dict]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM metric_anomalies ORDER BY detected_at DESC LIMIT ?", (int(limit),)).fetchall()]
        finally:
            con.close()

    def insert_anomaly(self, target_id: int, definition_id: int, value: float, zscore: float, severity: str = "warning") -> None:
        sev = "critical" if zscore >= 3 else "warning"
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("INSERT INTO metric_anomalies(target_id, definition_id, value, zscore, severity) VALUES(?,?,?,?,?)", (target_id, definition_id, float(value), float(zscore), sev))
            con.commit()
        finally:
            con.close()

    def import_targets_from_yaml(self, cfg: Dict[str, Any]) -> None:
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("DELETE FROM metric_samples")
            con.execute("DELETE FROM metric_definitions")
            con.execute("DELETE FROM targets")
            for t in cfg.get("targets", []):
                cur = con.execute(
                    "INSERT INTO targets(name, kind, address, probe_type, tier, ssh_key, enabled) VALUES(?,?,?,?,?,?,1)",
                    (
                        t["name"],
                        t.get("kind", "lxc"),
                        t.get("address", t["name"]),
                        t.get("probe_type", t.get("kind", "lxc")),
                        t.get("tier", "T2"),
                        t.get("ssh_key"),
                    ),
                )
                target_id = cur.lastrowid
                for m in t.get("metrics", []):
                    params = {k: m[k] for k in ("service_name", "container_name", "interface") if k in m}
                    con.execute(
                        "INSERT INTO metric_definitions(target_id, name, unit, poll_interval_sec, enabled, params) VALUES(?,?,?,?,?,?)",
                        (target_id, m["name"], m.get("unit"), int(m.get("interval_sec", 60)), 1, json.dumps(params) if params else None),
                    )
            con.commit()
        finally:
            con.close()
