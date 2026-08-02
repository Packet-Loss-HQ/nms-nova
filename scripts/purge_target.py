#!/usr/bin/env python3
"""Remove a target and all its metric_samples from SQLite."""
import os
import sys
from pathlib import Path
import sqlite3

DEFAULT_DB = Path(__file__).resolve().parent.parent / "state" / "nms-nova.db"


def purge(db_path: str, target_name: str) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute("SELECT id FROM targets WHERE name = ?", (target_name,))
        row = cur.fetchone()
        if not row:
            print(f"target not found: {target_name}")
            sys.exit(1)
        target_id = row[0]
        con.execute("DELETE FROM metric_samples WHERE target_id = ?", (target_id,))
        con.execute("DELETE FROM metric_definitions WHERE target_id = ?", (target_id,))
        con.execute("DELETE FROM targets WHERE id = ?", (target_id,))
        con.commit()
        print(f"purged target={target_name} target_id={target_id}")
    finally:
        con.close()


if __name__ == "__main__":
    db = os.getenv("NMS_DB", str(DEFAULT_DB))
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <target_name>")
        sys.exit(2)
    purge(db, sys.argv[1])
