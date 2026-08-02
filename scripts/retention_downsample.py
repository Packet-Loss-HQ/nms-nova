#!/usr/bin/env python3
"""
NMS-Nova retention + down-sampling job.
- Delete raw samples older than 30 days.
- Create 1-hour averaged aggregates for historical window.
Designed to run daily via cron or systemd timer.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def retention_cleanup(db_path: Path, retention_days: int = 30) -> int:
    con = sqlite3.connect(db_path)
    try:
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        cur = con.execute(
            "DELETE FROM metric_samples WHERE timestamp < ?",
            (cutoff.isoformat(),),
        )
        deleted = cur.rowcount
        con.commit()
        return deleted
    finally:
        con.close()


def downsample(db_path: Path, lookback_days: int = 30) -> int:
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_samples_hourly (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                definition_id INTEGER NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                value REAL NOT NULL,
                FOREIGN KEY(target_id) REFERENCES targets(id),
                FOREIGN KEY(definition_id) REFERENCES metric_definitions(id)
            )
            """
        )
        con.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_metric_samples_hourly_unique
            ON metric_samples_hourly(target_id, definition_id, timestamp)
            """
        )
        con.commit()

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        rows = con.execute(
            """
            SELECT ms.target_id,
                   ms.definition_id,
                   strftime('%Y-%m-%d %H:00:00', ms.timestamp) AS hour_bucket,
                   avg(ms.value) AS avg_value
            FROM metric_samples ms
            JOIN metric_definitions md ON md.id = ms.definition_id
            WHERE ms.timestamp >= ?
            GROUP BY ms.target_id, ms.definition_id, hour_bucket
            """,
            (cutoff.isoformat(),),
        ).fetchall()

        inserted = 0
        for target_id, definition_id, hour_bucket, avg_value in rows:
            try:
                con.execute(
                    "INSERT OR IGNORE INTO metric_samples_hourly(target_id, definition_id, timestamp, value) VALUES(?,?,?,?)",
                    (target_id, definition_id, hour_bucket, avg_value),
                )
                inserted += 1
            except Exception:
                pass
        con.commit()
        return inserted
    finally:
        con.close()


def main() -> int:
    db_path = Path(__file__).resolve().parent.parent / "state" / "nms-nova.db"
    print(f"cleanup: {retention_cleanup(db_path)} samples deleted")
    print(f"downsample: {downsample(db_path)} hourly rows created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
