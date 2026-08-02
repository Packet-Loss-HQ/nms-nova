#!/usr/bin/env python3
"""
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
            con.execute("DELETE FROM metric_samples WHERE timestamp < ?", (cutoff.isoformat(),))
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
        allowed = {"name", "kind", "address", "probe_type", "tier", "enabled"}
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
