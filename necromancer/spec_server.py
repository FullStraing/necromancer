"""A cloud server driven entirely by a recovered ProtocolSpec, with optional *mutations*.

Mutations deliberately violate one hypothesis so the original client can act as an oracle:
if the client still works, the client does not enforce that property; if it fails, it does.
"""
from __future__ import annotations

import asyncio
import os
import struct
import time

from .crc import BY_NAME
from .spec import ProtocolSpec

MUTATIONS = {
    "seq_high": "server seq starts at 0x0101 (tests which length-field candidate is real)",
    "seq_frozen": "server seq never increments",
    "seq_start_random": "server seq starts at a random value",
    "ack_wrong_seq": "ACK echoes a wrong request seq",
    "ack_wrong_type": "ACK echoes a wrong request type",
    "status_stale": "STATUS ignores previous SET commands",
    "auth_ok_zero": "AUTH_OK payload is all zeros",
    "crc_swapped": "checksum stored with the other endianness",
    "doc_length_be": "length field big-endian, as the manual claims",
    "doc_crc_full": "checksum over the entire frame incl. prefix, as the manual claims",
    "doc_ack_0x80": "ACK type code 0x80, as the manual claims",
}


class SpecCodec:
    def __init__(self, spec: ProtocolSpec, mutations: frozenset[str] = frozenset()):
        self.spec = spec
        self.m = mutations
        self.crc = BY_NAME[spec.crc_algo]

    def encode(self, ftype: int, seq: int, payload: bytes) -> bytes:
        s = self.spec
        header = bytearray(s.header_len)
        prefix = bytes.fromhex(s.prefix_hex)
        header[: len(prefix)] = prefix
        header[s.type_off] = ftype
        header[s.seq_off:s.seq_off + 2] = seq.to_bytes(2, s.seq_endian)
        len_endian = "big" if "doc_length_be" in self.m else s.len_endian
        header[s.len_off:s.len_off + 2] = len(payload).to_bytes(2, len_endian)
        body = bytes(header) + payload
        start = 0 if "doc_crc_full" in self.m else s.crc_start
        crc_endian = s.crc_endian if "crc_swapped" not in self.m else ("big" if s.crc_endian == "little" else "little")
        return body + self.crc.compute(body[start:]).to_bytes(2, crc_endian)

    async def read(self, reader) -> tuple[int, int, bytes]:
        s = self.spec
        head = await reader.readexactly(s.header_len)
        length = int.from_bytes(head[s.len_off:s.len_off + 2], s.len_endian)
        rest = await reader.readexactly(length + 2)
        payload = rest[:length]
        return head[s.type_off], int.from_bytes(head[s.seq_off:s.seq_off + 2], s.seq_endian), payload


class SpecServer:
    def __init__(self, spec: ProtocolSpec, mutations: frozenset[str] = frozenset(), power_rule: str = "brightness_nonzero"):
        unknown = mutations - MUTATIONS.keys()
        if unknown:
            raise ValueError(f"unknown mutations: {sorted(unknown)}")
        self.spec = spec
        self.codec = SpecCodec(spec, mutations)
        self.m = mutations
        self.power_rule = power_rule
        self.lamps: dict[bytes, bytes] = {}
        self._server: asyncio.base_events.Server | None = None

    async def start(self, port: int = 0) -> int:
        self._server = await asyncio.start_server(self._on_conn, "127.0.0.1", port)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def _status_after(self, status: bytes, field: str, value: bytes) -> bytes:
        off, width = self.spec.status_fields[field]
        new = status[:off] + value[:width] + status[off + width:]
        if field == "brightness" and self.power_rule == "brightness_nonzero":
            new = bytes([int(value[0] > 0)]) + new[1:]
        return new

    async def _on_conn(self, reader, writer) -> None:
        s, c = self.spec, self.spec.codes
        seq = {"seq_high": 0x0100, "seq_start_random": int.from_bytes(os.urandom(2), "little") | 0x10}.get(
            next((m for m in ("seq_high", "seq_start_random") if m in self.m), ""), s.seq_start - 1)
        device, nonce = b"", b""

        async def send(ftype: int, payload: bytes) -> None:
            nonlocal seq
            if "seq_frozen" not in self.m:
                seq = (seq + 1) & 0xFFFF
            writer.write(self.codec.encode(ftype, seq, payload))
            await writer.drain()

        try:
            while True:
                ftype, rseq, payload = await self.codec.read(reader)
                if ftype == c["hello"]:
                    device, nonce = payload[:8], os.urandom(s.payload_sizes.get("challenge", 4))
                    await send(c["challenge"], nonce)
                elif ftype == c["auth"]:
                    body = b"\0" * 6 if "auth_ok_zero" in self.m else struct.pack("<HI", int.from_bytes(os.urandom(2), "little"), int(time.time()))
                    await send(c["auth_ok"], body)
                elif ftype == c["get_status"]:
                    st = self.lamps.get(device, bytes.fromhex(s.default_status_hex))
                    if "status_stale" in self.m:
                        st = bytes.fromhex(s.default_status_hex)
                    await send(c["status"], st)
                elif ftype in (c["set_brightness"], c["set_color"]):
                    if ftype == c["set_brightness"] and payload[0] > s.brightness_max and "error" in c:
                        await send(c["error"], bytes([3]) + rseq.to_bytes(2, "little"))
                        continue
                    field = "brightness" if ftype == c["set_brightness"] else "color"
                    st = self.lamps.get(device, bytes.fromhex(s.default_status_hex))
                    self.lamps = {**self.lamps, device: self._status_after(st, field, payload)}
                    ack_seq = (rseq + 7) & 0xFFFF if "ack_wrong_seq" in self.m else rseq
                    ack_type = 0x7F if "ack_wrong_type" in self.m else ftype
                    body = bytearray(s.payload_sizes.get("ack", 3))
                    body[s.ack_seq_off:s.ack_seq_off + 2] = ack_seq.to_bytes(2, "little")
                    if s.ack_type_off is not None:
                        body[s.ack_type_off] = ack_type
                    await send(0x80 if "doc_ack_0x80" in self.m else c["ack"], bytes(body))
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
