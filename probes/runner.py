#!/usr/bin/env python3
"""
NMS-Nova probe runner.
Read-only execution against targets via lxc-attach or SSH.
"""

import base64
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProbeResult:
    target_id: int
    definition_id: int
    value: float
    stale: bool = False
    error: Optional[str] = None


class ProbeRunner:
    def __init__(self, timeout_sec: int = 10, ssh_user: str = "root", ssh_key: Optional[str] = None):
        self.timeout_sec = timeout_sec
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key

    def run(self, command: str, target_kind: str, target_address: str, ssh_key: Optional[str] = None) -> str:
        key = ssh_key or self.ssh_key
        if target_kind == "lxc":
            args = ["lxc-attach", "-n", target_address, "--", "bash", "-c", command]
        elif target_kind == "ssh":
            args = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
            ]
            if key:
                args.extend(["-i", key])
            args.append(f"{self.ssh_user}@{target_address}")
            args.append(command)
        else:
            raise ValueError(f"Unsupported target kind: {target_kind}")

        try:
            out = subprocess.check_output(args, stderr=subprocess.STDOUT, timeout=self.timeout_sec)
            return out.decode("utf-8", errors="replace").strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError("probe timeout")
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"probe failed: {exc.output.decode('utf-8', errors='replace').strip()}")


def _remote_python(runner: ProbeRunner, target_kind: str, target_address: str, code: str) -> str:
    payload = base64.b64encode(code.encode("utf-8")).decode("ascii")
    cmd = f"echo {payload} | base64 -d | python3"
    return runner.run(cmd, target_kind, target_address)
