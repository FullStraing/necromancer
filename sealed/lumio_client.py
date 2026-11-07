"""Lumio Home app — the ORIGINAL client (shipped as bytecode-only evidence/client/lumio_app.pyz).

Usage: python lumio_app.pyz --port 7000 [--device ID] [--json] [--legacy] CMD...
  CMD: status | brightness=N | color=RRGGBB
"""
from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys

from lumio_proto import (
    ACK, AUTH, AUTH_OK, CHALLENGE, ERROR, GET_STATUS, HELLO, SET_BRIGHTNESS, SET_COLOR, STATUS,
    Frame, ProtocolError, auth_token, encode, read_frame,
)

ERRORS = {1: "checksum rejected by cloud", 2: "authentication failed", 3: "value out of range", 4: "unknown command"}
TIMEOUT = 2.0


class Fatal(Exception):
    pass


class Link:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.seq = 0
        self.server_seq = None

    async def request(self, ftype: int, payload: bytes, expect: int) -> tuple[int, Frame]:
        self.seq = (self.seq + 1) & 0xFFFF
        self.writer.write(encode(Frame(ftype, self.seq, payload)))
        await self.writer.drain()
        try:
            f = await asyncio.wait_for(read_frame(self.reader), TIMEOUT)
        except ProtocolError as e:
            raise Fatal(str(e))
        except asyncio.TimeoutError:
            raise Fatal("cloud did not answer (timeout)")
        except (asyncio.IncompleteReadError, ConnectionError):
            raise Fatal("cloud closed the connection")
        if self.server_seq is not None and f.seq != (self.server_seq + 1) & 0xFFFF:
            raise Fatal("sequence error: replayed or out-of-order frame")
        self.server_seq = f.seq
        if f.type == ERROR:
            code, echo = struct.unpack("<BH", f.payload[:3])
            if echo != self.seq:
                raise Fatal("error frame for unknown request")
            return self.seq, f
        if f.type != expect:
            raise Fatal(f"unexpected reply type 0x{f.type:02x}")
        return self.seq, f


def parse_cmds(cmds: list[str], legacy: bool) -> list[tuple]:
    out = []
    for c in cmds:
        if c == "status":
            out.append(("status",))
        elif c.startswith("brightness="):
            v = int(c.split("=", 1)[1])
            if not legacy and not 0 <= v <= 100:
                raise SystemExit("brightness must be 0..100")
            out.append(("brightness", v))
        elif c.startswith("color="):
            h = c.split("=", 1)[1]
            out.append(("color", bytes.fromhex(h)))
        else:
            raise SystemExit(f"unknown command {c}")
    return out


async def run(host: str, port: int, device: bytes, cmds: list[tuple]) -> dict:
    report = {"ok": True, "events": [], "lamp": None, "error": None}
    expected = {}
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT)
    except (OSError, asyncio.TimeoutError):
        return {**report, "ok": False, "error": "cannot reach Lumio Cloud"}
    link = Link(reader, writer)
    try:
        _, ch = await link.request(HELLO, device + struct.pack("<H", 0x0107), CHALLENGE)
        if ch.type == ERROR or len(ch.payload) != 4:
            raise Fatal("handshake failed: bad challenge")
        _, ok = await link.request(AUTH, auth_token(ch.payload), AUTH_OK)
        if ok.type == ERROR:
            raise Fatal("authentication failed")
        if len(ok.payload) < 6:
            raise Fatal("handshake failed: short auth reply")
        report["events"].append("connected")
        for cmd in cmds:
            if cmd[0] == "status":
                _, st = await link.request(GET_STATUS, b"", STATUS)
                if st.type == ERROR:
                    raise Fatal(ERRORS.get(st.payload[0], "cloud error"))
                if len(st.payload) != 5:
                    raise Fatal("malformed status")
                lamp = {"power": bool(st.payload[0]), "brightness": st.payload[1], "color": st.payload[2:5].hex()}
                for k, v in expected.items():
                    if lamp[k] != v:
                        raise Fatal(f"lamp state mismatch on {k}")
                report["lamp"] = lamp
                report["events"].append(f"status {lamp}")
                continue
            ftype, payload = (SET_BRIGHTNESS, bytes([cmd[1] & 0xFF])) if cmd[0] == "brightness" else (SET_COLOR, cmd[1])
            seq, r = await link.request(ftype, payload, ACK)
            if r.type == ERROR:
                report["events"].append(f"rejected {cmd[0]}: {ERRORS.get(r.payload[0], 'cloud error')}")
                continue
            if len(r.payload) < 2 or struct.unpack("<H", r.payload[:2])[0] != seq:
                raise Fatal("ack does not match request")
            if cmd[0] == "brightness":
                expected.update(brightness=cmd[1], power=cmd[1] > 0)
            else:
                expected["color"] = cmd[1].hex()
            report["events"].append(f"ok {cmd[0]}")
    except Fatal as e:
        report = {**report, "ok": False, "error": str(e)}
    finally:
        writer.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(prog="lumio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7070)
    ap.add_argument("--device", default="4c554d0000c0ffee")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--legacy", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("cmds", nargs="*", default=["status"])
    a = ap.parse_args()
    report = asyncio.run(run(a.host, a.port, bytes.fromhex(a.device), parse_cmds(a.cmds, a.legacy)))
    if a.json:
        print(json.dumps(report))
    else:
        for e in report["events"]:
            print(f"  {e}")
        if report["ok"]:
            lamp = report["lamp"]
            print(f"💡 Lamp online{': ' + str(lamp) if lamp else ''}")
        else:
            print(f"❌ Lumio: {report['error']}")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
