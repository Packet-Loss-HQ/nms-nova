#!/usr/bin/env python3
"""
NMS-Nova poll loop.
Reads targets + metric definitions from SQLite, runs probes on tier-aware intervals,
writes samples to SQLite. Designed to run as a container PID 1 or cron.
"""

import json
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


def _resolve_vars(cfg: dict[str, Any]) -> dict[str, Any]:
    defaults = cfg.get("defaults", {})
    text = yaml.safe_dump(cfg, default_flow_style=False)
    for key, value in defaults.items():
        text = text.replace(f"${{{key}}}", str(value))
    return yaml.safe_load(text)


def migrate_yaml_if_needed(store: MetricsStore, targets_path: Path) -> None:
    targets = store.list_targets()
    if targets:
        return
    if not targets_path.exists():
        return
    cfg = _resolve_vars(yaml.safe_load(targets_path.read_text()))
    if not cfg.get("targets"):
        return
    log.info("migrating targets.yaml -> sqlite")
    store.import_targets_from_yaml(cfg)


def run_once(store: MetricsStore, runner: ProbeRunner) -> None:
    targets = store.list_targets()
    if not targets:
        log.warning("no targets configured")
        return

    target_map = {}
    for t in targets:
        if not t.get("enabled", 1):
            continue
        target_map[t["name"]] = t

    latest = store.latest_samples()
    target_ids = {row["target_name"]: row["target_id"] for row in latest}

    con = __import__("sqlite3").connect(store.db_path)
    con.row_factory = __import__("sqlite3").Row
    try:
        existing_defs = {}
        for row in con.execute("SELECT id, target_id, name, params FROM metric_definitions").fetchall():
            existing_defs[(row["target_id"], row["name"])] = row["id"]

        for name, t in target_map.items():
            metrics = store.list_metrics_for_target(t["id"])
            for m in metrics:
                key = (t["id"], m["name"])
                if key not in existing_defs:
                    cur = con.execute(
                        "INSERT INTO metric_definitions(target_id, name, unit, poll_interval_sec, enabled, params) VALUES(?,?,?,?,?,?)",
                        (t["id"], m["name"], m.get("unit"), int(m.get("poll_interval_sec", 60)), 1, m.get("params")),
                    )
                    existing_defs[key] = cur.lastrowid
        con.commit()
    finally:
        con.close()

    for name, t in target_map.items():
        tid = t["id"]
        metrics = store.list_metrics_for_target(tid)
        runner = ProbeRunner(
            timeout_sec=10,
            ssh_key=t.get("ssh_key"),
        )
        for m in metrics:
            key = (tid, m["name"])
            if key not in existing_defs:
                continue
            definition_id = existing_defs[key]
            fn = PROBE_MAP.get(m["name"])
            if not fn:
                continue
            probe_kwargs = {}
            if m.get("params"):
                try:
                    probe_kwargs = json.loads(m["params"])
                except Exception:
                    probe_kwargs = {}
            try:
                result = fn(
                    runner,
                    target_id=tid,
                    definition_id=definition_id,
                    target_kind=t.get("kind", "lxc"),
                    target_address=t.get("address", name),
                    service_name=probe_kwargs.get("service_name", ""),
                    container_name=probe_kwargs.get("container_name", ""),
                    interface=probe_kwargs.get("interface", "eth0"),
                    **{k: v for k, v in probe_kwargs.items() if k not in ("service_name", "container_name", "interface")},
                )
                store.insert_sample(result.target_id, result.definition_id, result.value, error=result.error)
            except Exception as exc:
                log.exception("probe_failed target=%s metric=%s", name, m["name"])
                store.insert_sample(tid, definition_id, 0.0, error=str(exc))


class PollLoop:
    def __init__(self, db_path: Path, poll_interval: int = 30):
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
                run_once(self.store, self.runner)
            except Exception:
                pass
            time.sleep(self.poll_interval)


def main() -> int:
    db_path = Path(os.getenv("NMS_DB", "state/nms-nova.db"))
    targets_path = Path(os.getenv("NMS_TARGETS", str(DEFAULT_TARGETS_PATH)))
    poll_interval = int(os.getenv("NMS_POLL_INTERVAL", "30"))

    store = MetricsStore(str(db_path))
    migrate_yaml_if_needed(store, targets_path)

    PollLoop(db_path=db_path, poll_interval=poll_interval).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
