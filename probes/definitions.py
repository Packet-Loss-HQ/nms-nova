#!/usr/bin/env python3
"""
Built-in probe definitions for NMS-Nova.
Each returns a numeric sample value or raises.
"""

from probes.runner import ProbeRunner, ProbeResult, _remote_python


def probe_cpu_usage(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, **_kwargs) -> ProbeResult:
    code = (
        "import os; "
        "s=os.popen('cat /proc/stat').read().splitlines(); "
        "c=[l for l in s if l.startswith('cpu ')][0].split()[1:8]; "
        "vals=list(map(float,c)); "
        "idle=vals[3]; total=sum(vals); "
        "print(f'{((total-idle)/total)*100:.1f}' if total else '0.0')"
    )
    try:
        value = float(_remote_python(runner, target_kind, target_address, code))
    except Exception:
        value = 0.0
    return ProbeResult(target_id=target_id, definition_id=definition_id, value=value)


def probe_memory_used_percent(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, **_kwargs) -> ProbeResult:
    code = (
        "import os; vals={}; "
        "[vals.update({line.split(':')[0].strip(): int(line.split(':')[1].strip().split()[0])}) "
        "for line in open('/proc/meminfo')]; "
        "used=vals.get('MemTotal',1)-vals.get('MemAvailable',vals.get('MemFree',0)); "
        "print(f\"{used/vals.get('MemTotal',1)*100:.1f}\")"
    )
    try:
        value = float(_remote_python(runner, target_kind, target_address, code))
    except Exception:
        value = 0.0
    return ProbeResult(target_id=target_id, definition_id=definition_id, value=value)


def probe_disk_root_used_percent(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, **_kwargs) -> ProbeResult:
    code = "import os; s=os.popen('df --output=pcent /').read().splitlines(); print(s[-1].replace('%','').strip() if s else '0')"
    try:
        value = float(_remote_python(runner, target_kind, target_address, code))
    except Exception:
        value = 0.0
    return ProbeResult(target_id=target_id, definition_id=definition_id, value=value)


def probe_service_up(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, service_name: str = "", container_name: str = "", **_kwargs) -> ProbeResult:
    value = 0.0
    error = None
    if service_name:
        code = f"import subprocess,sys; r=subprocess.run(['systemctl','is-active',{repr(service_name)}],capture_output=True,text=True); print('active' if r.returncode==0 else 'inactive')"
        try:
            raw = _remote_python(runner, target_kind, target_address, code)
            if raw == "active":
                value = 1.0
        except Exception as exc:
            error = str(exc)
    if value == 0.0 and container_name:
        code = (
            "import subprocess,sys;"
            " r=subprocess.run(['docker','inspect','--format','{{.State.Status}}'," + repr(container_name) + "],"
            "capture_output=True,text=True);"
            " print((r.stdout or 'missing').strip())"
        )
        try:
            raw = _remote_python(runner, target_kind, target_address, code)
            status = raw.strip().strip('"')
            if status == "running":
                value = 1.0
        except Exception as exc:
            error = str(exc)
    if value == 0.0 and error:
        return ProbeResult(target_id=target_id, definition_id=definition_id, value=0.0, error=error)
    return ProbeResult(target_id=target_id, definition_id=definition_id, value=value)


def probe_load_avg(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, **_kwargs) -> ProbeResult:
    code = "print(open('/proc/loadavg').read().split()[0])"
    try:
        value = float(_remote_python(runner, target_kind, target_address, code))
    except Exception:
        value = 0.0
    return ProbeResult(target_id=target_id, definition_id=definition_id, value=value)


def probe_interface_stats(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, interface: str = "eth0", **_kwargs) -> ProbeResult:
    code = (
        "import os; "
        "lines=open('/proc/net/dev').read().splitlines(); "
        "row=[l.split() for l in lines if l.strip().split(':')[0].strip() == '" + interface + "'][0]; "
        "print(f'{row[1]} {row[9]}')"
    )
    try:
        raw = _remote_python(runner, target_kind, target_address, code)
        rx_bytes, tx_bytes = map(int, raw.split())
        value = float((rx_bytes + tx_bytes) / 1024.0)
    except Exception:
        value = 0.0
    return ProbeResult(target_id=target_id, definition_id=definition_id, value=value)
