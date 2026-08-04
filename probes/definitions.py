#!/usr/bin/env python3
"""
Built-in probe definitions for NMS-Nova.
Each returns a numeric sample value or raises.
"""

from probes.runner import ProbeRunner, ProbeResult, _remote_python, _snmp_run


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


if False:  # keep import side-effect in one place
    try:
        from pysnmp.hlapi import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            getCmd,
            UsmUserData,
            usmHMACSHAAuthProtocol,
            usmDESPrivProtocol,
        )

        _PYSNMP_AVAILABLE = True
    except Exception:
        _PYSNMP_AVAILABLE = False


def _require_pysnmp():
    try:
        from pysnmp.hlapi import (  # noqa: F401
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            getCmd,
            UsmUserData,
            usmHMACSHAAuthProtocol,
            usmDESPrivProtocol,
        )
    except Exception as exc:
        raise RuntimeError("pysnmp is not installed") from exc


def _snmp_get(target_address, oid, community="public", version=2, v3_user=None, v3_auth=None, v3_priv=None, v3_auth_key=None, v3_priv_key=None, timeout=5, retries=1):
    if not _PYSNMP_AVAILABLE:
        raise RuntimeError("pysnmp is not installed")
    auth = CommunityData(community, mpModel=0 if version == 1 else 1)
    if version == 3 and v3_user:
        if v3_auth and v3_auth_key:
            auth = UsmUserData(
                v3_user,
                authKey=v3_auth_key,
                privKey=v3_priv_key or "",
                authProtocol=usmHMACSHAAuthProtocol,
                privProtocol=usmDESPrivProtocol if v3_priv else None,
            )
        else:
            auth = UsmUserData(v3_user)
    iterator = getCmd(
        SnmpEngine(),
        auth,
        UdpTransportTarget((target_address, 161), timeout=timeout, retries=retries),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    error_indication, error_status, error_index, var_binds = next(iterator)
    if error_indication or error_status:
        raise RuntimeError(str(error_indication or error_status.prettyPrint()))
    for _name, val in var_binds:
        return val.prettyPrint()
    raise RuntimeError("SNMP response empty")


def probe_snmp_sys_descr(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, **kwargs) -> ProbeResult:
    community = kwargs.get("snmp_community") or "public"
    version = kwargs.get("snmp_version", "2c")
    v3_user = kwargs.get("snmp_v3_user")
    v3_auth = kwargs.get("snmp_v3_auth")
    v3_priv = kwargs.get("snmp_v3_priv")
    v3_auth_key = kwargs.get("snmp_v3_auth_key")
    v3_priv_key = kwargs.get("snmp_v3_priv_key")
    try:
        raw = _snmp_run(
            target_address,
            "1.3.6.1.2.1.1.1.0",
            community=community,
            snmp_version=version,
            v3_user=v3_user,
            v3_auth=v3_auth,
            v3_priv=v3_priv,
            v3_auth_key=v3_auth_key,
            v3_priv_key=v3_priv_key,
            timeout_sec=runner.timeout_sec,
        )
        return ProbeResult(target_id=target_id, definition_id=definition_id, value=1.0 if raw else 0.0)
    except Exception as exc:
        return ProbeResult(target_id=target_id, definition_id=definition_id, value=0.0, error=str(exc))


def probe_snmp_sys_up_time(runner: ProbeRunner, target_id: int, definition_id: int, target_kind: str, target_address: str, **kwargs) -> ProbeResult:
    community = kwargs.get("snmp_community") or "public"
    version = kwargs.get("snmp_version", "2c")
    v3_user = kwargs.get("snmp_v3_user")
    v3_auth = kwargs.get("snmp_v3_auth")
    v3_priv = kwargs.get("snmp_v3_priv")
    v3_auth_key = kwargs.get("snmp_v3_auth_key")
    v3_priv_key = kwargs.get("snmp_v3_priv_key")
    try:
        raw = _snmp_run(
            target_address,
            "1.3.6.1.2.1.1.3.0",
            community=community,
            snmp_version=version,
            v3_user=v3_user,
            v3_auth=v3_auth,
            v3_priv=v3_priv,
            v3_auth_key=v3_auth_key,
            v3_priv_key=v3_priv_key,
            timeout_sec=runner.timeout_sec,
        )
        ticks = int(raw.split()[0]) if raw and raw.split() else 0
        return ProbeResult(target_id=target_id, definition_id=definition_id, value=float(ticks))
    except Exception as exc:
        return ProbeResult(target_id=target_id, definition_id=definition_id, value=0.0, error=str(exc))
