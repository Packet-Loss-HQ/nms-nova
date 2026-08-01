#!/usr/bin/env python3
"""
NMS-Nova poll loop.
Reads targets + metric definitions, runs probes on tier-aware intervals,
writes samples to SQLite. Designed to run as a container PID 1 or cron.
"""

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nms-nova.poller")

import os
import time
import signal
import sys
from pathlib import Path
from typing import Any

import yaml

from probes.definitions import (
    probe_cpu_usage,
    probe_disk_root_used_percent,
    probe_interface_stats,
    probe_load_avg,
    probe_memory_used_percent,
    probe_service_up,
)
from probes.runner import ProbeRunner
from state.store import MetricsStore

PROBE_MAP = {
    "cpu_usage_percent": probe_cpu_usage,
    "memory_used_percent": probe_memory_used_percent,
    "disk_root_used_percent": probe_disk_root_used_percent,
    "service_up": probe_service_up,
    "load_avg_1m": probe_load_avg,
    "interface_total_kbps": probe_interface_stats,
}

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS_PATH = BASE_DIR / "targets.yaml"


def load_targets(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"targets": []}
    return yaml.safe_load(path.read_text())


def build_target_map(targets_cfg: dict[str, Any]) -> dict[str, dict]:
    out = {}
    for t in targets_cfg.get("targets", []):
        out[t["name"]] = t
    return out


def validate_targets(cfg: dict[str, Any]) -> list[str]:
    errors = []
    targets = cfg.get("targets", [])
    if not isinstance(targets, list):
        return ["targets must be a list"]
    seen = set()
    for idx, t in enumerate(targets):
        prefix = f"targets[{idx}]"
        if not isinstance(t, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        name = t.get("name")
        if not name or not isinstance(name, str):
            errors.append(f"{prefix}.name is required")
        elif name in seen:
            errors.append(f"{prefix}.name '{name}' is duplicated")
        else:
            seen.add(name)
        for key in ("address", "kind", "probe_type", "tier"):
            if key not in t:
                errors.append(f"{prefix}.{key} is required")
        metrics = t.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            errors.append(f"{prefix}.metrics must be a non-empty list")
            continue
        for m_idx, m in enumerate(metrics):
            m_prefix = f"{prefix}.metrics[{m_idx}]"
            if not isinstance(m, dict):
                errors.append(f"{m_prefix} must be a mapping")
                continue
            if "name" not in m:
                errors.append(f"{m_prefix}.name is required")
            if "interval_sec" not in m:
                errors.append(f"{m_prefix}.interval_sec is required")
            elif not isinstance(m["interval_sec"], int):
                errors.append(f"{m_prefix}.interval_sec must be int")
    return errors


def run_once(store: MetricsStore, targets_path: Path, runner: ProbeRunner) -> None:
    cfg = load_targets(targets_path)
    target_map = build_target_map(cfg)

    for name, t in target_map.items():
        store.upsert_target(
            name=name,
            kind=t.get("kind", "lxc"),
            address=t.get("address", name),
            probe_type=t.get("probe_type", t.get("kind", "lxc")),
            tier=t.get("tier", "T2"),
        )

    latest = store.latest_samples()
    target_ids = {row["target_name"]: row["target_id"] for row in latest}
    for name in target_map:
        if name not in target_ids:
            tid = store.upsert_target(
                name=name,
                kind=target_map[name].get("kind", "lxc"),
                address=target_map[name].get("address", name),
                probe_type=target_map[name].get("probe_type", target_map[name].get("kind", "lxc")),
                tier=target_map[name].get("tier", "T2"),
            )
            target_ids[name] = tid

    con = __import__("sqlite3").connect(store.db_path)
    con.row_factory = __import__("sqlite3").Row
    try:
        existing_defs = {}
        for row in con.execute("SELECT id, target_id, name FROM metric_definitions").fetchall():
            existing_defs[(row["target_id"], row["name"])] = row["id"]
        for name, t in target_map.items():
            tid = target_ids[name]
            for m in t.get("metrics", []):
                key = (tid, m["name"])
                if key not in existing_defs:
                    cur = con.execute(
                        "INSERT INTO metric_definitions(target_id, name, unit, poll_interval_sec) VALUES(?,?,?,?)",
                        (tid, m["name"], m.get("unit"), int(m.get("interval_sec", 60))),
                    )
                    existing_defs[key] = cur.lastrowid
        con.commit()
    finally:
        con.close()

    for name, t in target_map.items():
        tid = target_ids[name]
        runner = ProbeRunner(
            timeout_sec=10,
            ssh_key=t.get("ssh_key"),
        )
        for m in t.get("metrics", []):
            key = (tid, m["name"])
            if key not in existing_defs:
                continue
            defn = existing_defs[key]
            fn = PROBE_MAP.get(m["name"])
            if not fn:
                continue
            try:
                result = fn(
                    runner,
                    target_id=tid,
                    definition_id=defn,
                    target_kind=t.get("kind", "lxc"),
                    target_address=t.get("address", name),
                    service_name=m.get("service_name", ""),
                )
                store.insert_sample(result.target_id, result.definition_id, result.value, error=result.error)
            except Exception as exc:
                log.exception("probe_failed target=%s metric=%s", name, m["name"])
                store.insert_sample(tid, defn, 0.0, error=str(exc))


class PollLoop:
    def __init__(self, targets_path: Path, db_path: Path, poll_interval: int = 30):
        self.targets_path = targets_path
        self.store = MetricsStore(str(db_path))
        self.runner = ProbeRunner(timeout_sec=10)
        self.poll_interval = poll_interval
        self._running = True

    def stop(self, sig_num: int, _frame: Any) -> None:
        self._running = False

    def start(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        while self._running:
            try:
                run_once(self.store, self.targets_path, self.runner)
            except Exception:
                pass
            time.sleep(self.poll_interval)


def main() -> int:
    targets_path = Path(os.getenv("NMS_TARGETS", str(DEFAULT_TARGETS_PATH)))
    db_path = Path(os.getenv("NMS_DB", "state/nms-nova.db"))
    poll_interval = int(os.getenv("NMS_POLL_INTERVAL", "30"))
    cfg = load_targets(targets_path)
    errors = validate_targets(cfg)
    if errors:
        print("targets.yaml validation failed:")
        for e in errors:
            print(f" - {e}")
        return 2
    PollLoop(targets_path=targets_path, db_path=db_path, poll_interval=poll_interval).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
