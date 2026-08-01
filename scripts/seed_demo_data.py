#!/usr/bin/env python3
"""Generate a demo dataset for NMS-Nova."""
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_DB = Path("/opt/nms-nova/state/nms-nova.db")


def main(db_path: Path = DEFAULT_DB) -> None:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    targets = [
        ("host-a", 0.5, 12.0, 14.0),
        ("host-b", 0.4, 10.0, 11.0),
        ("host-c", 0.4, 13.0, 22.0),
        ("host-d", 0.0, 0.0, 0.0),
        ("host-e", 0.0, 0.0, 0.0),
        ("host-f", 0.0, 0.0, 0.0),
        ("host-g", 0.0, 0.0, 0.0),
        ("host-h", 0.0, 0.0, 0.0),
    ]
    now = datetime.utcnow()
    rows = []
    for name, cpu_base, mem_base, disk_base in targets:
        target_id = cur.execute("SELECT id FROM targets WHERE name=?", (name,)).fetchone()
        if not target_id:
            continue
        target_id = target_id[0]
        defs = cur.execute("SELECT id, name FROM metric_definitions WHERE target_id=?", (target_id,)).fetchall()
        def_map = {n: d for d, n in defs}
        for minute in range(30 * 24 * 60):
            ts = now - timedelta(minutes=minute)
            cpu = max(0.0, min(100.0, cpu_base + random.uniform(-0.2, 0.2)))
            mem = max(0.0, min(100.0, mem_base + random.uniform(-1.0, 1.0)))
            disk = max(0.0, min(100.0, disk_base + random.uniform(-0.1, 0.1)))
            up = 1.0
            values = {"cpu_usage_percent": cpu, "memory_used_percent": mem, "disk_root_used_percent": disk, "service_up": up}
            for metric, value in values.items():
                def_id = def_map.get(metric)
                if def_id:
                    rows.append((target_id, def_id, ts.isoformat(), value))
    cur.executemany("INSERT INTO metric_samples (target_id, definition_id, timestamp, value) VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()
    print(f"SEEDED {len(rows)} rows")


if __name__ == "__main__":
    main()
