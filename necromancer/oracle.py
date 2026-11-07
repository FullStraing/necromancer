"""The original, unmodified client as a behavioral oracle (black box: we only run it and read its verdict)."""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .evidence import EVIDENCE_DIR
from .spec import ProtocolSpec
from .spec_server import SpecServer

CLIENT = EVIDENCE_DIR / "client" / "lumio_app.pyz"
DEFAULT_SCRIPT = ("status", "brightness=37", "color=12ab9f", "status")
CONFORMANCE_SCRIPTS: tuple[tuple[str, ...], ...] = (
    DEFAULT_SCRIPT,
    ("brightness=0", "status"),
    ("brightness=100", "color=000000", "status", "brightness=55", "status"),
    ("--legacy", "brightness=180", "status"),
    ("color=ffffff", "color=010203", "status"),
)


@dataclass(frozen=True)
class OracleResult:
    ok: bool
    error: str | None
    events: tuple[str, ...] = field(default_factory=tuple)
    lamp: dict | None = None


async def run_client(port: int, script: tuple[str, ...] = DEFAULT_SCRIPT, timeout: float = 15.0) -> OracleResult:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(CLIENT), "--port", str(port), "--json", *script,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return OracleResult(False, "client hung")
    try:
        rep = json.loads(out.decode().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return OracleResult(False, f"client crashed: {err.decode()[-300:]}")
    return OracleResult(bool(rep["ok"]), rep.get("error"), tuple(rep.get("events", [])), rep.get("lamp"))


async def probe(spec: ProtocolSpec, mutations: frozenset[str] = frozenset(),
                script: tuple[str, ...] = DEFAULT_SCRIPT, power_rule: str = "brightness_nonzero") -> OracleResult:
    server = SpecServer(spec, mutations, power_rule)
    port = await server.start()
    try:
        return await run_client(port, script)
    finally:
        await server.stop()


async def conformance_on_port(port: int) -> list[tuple[tuple[str, ...], OracleResult]]:
    return [(sc, await run_client(port, sc)) for sc in CONFORMANCE_SCRIPTS]


async def dead_cloud_check(port: int = 7070) -> OracleResult:
    return await run_client(port, ("status",))


def client_path() -> Path:
    return CLIENT
