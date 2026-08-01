#!/usr/bin/env python3
"""NMS-Nova SQLite backup/restore utility."""
import argparse
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path("/opt/nms-nova/state/nms-nova.db")


def backup(db_path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"nms-nova-{stamp}.db"
    con = sqlite3.connect(db_path)
    try:
        con.execute("VACUUM")
    finally:
        con.close()
    shutil.copy2(db_path, dest)
    print(f"BACKUP OK {dest} ({dest.stat().st_size} bytes)")
    return dest


def restore(backup_path: Path, db_path: Path) -> None:
    if not backup_path.exists():
        raise FileNotFoundError(f"backup not found: {backup_path}")
    tmp = db_path.with_suffix(".restore-tmp.db")
    shutil.copy2(backup_path, tmp)
    try:
        con = sqlite3.connect(tmp)
        try:
            con.execute("PRAGMA integrity_check")
        finally:
            con.close()
        db_path.replace(db_path.with_suffix(".bak-before-restore.db"))
        tmp.replace(db_path)
        print(f"RESTORE OK {db_path}")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["backup", "restore"])
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dest-dir", default="/opt/nms-nova/backups")
    p.add_argument("--file")
    args = p.parse_args()
    db = Path(args.db)
    if args.action == "backup":
        backup(db, Path(args.dest_dir))
    else:
        restore(Path(args.file), db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
