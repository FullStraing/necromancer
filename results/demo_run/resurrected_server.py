#!/usr/bin/env python3
"""Replacement cloud server for the "Lumio" smart lamp.

Reconstructed wire protocol (all multi-byte fields little-endian):

    +--------+------+---------+---------+---------+----------+
    | 4c4d02 | type | seq u16 | len u16 | payload | crc u16  |
    +--------+------+---------+---------+---------+----------+
      0..2     3      4..5      6..7      8...      last 2

* len field  = payload length (total frame length - 10)
* crc        = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection,
               xorout 0) over bytes [2 : 8 + len(payload)], appended LE
* seq        = per-direction counter; the server starts at 1, +1 per frame
* handshake  = HELLO -> CHALLENGE(4 random nonce bytes); the AUTH payload must
               equal reversed(nonce) XOR 0x5A -> AUTH_OK(session id, unix time)
* lamp state = (power, brightness, RGB) per device id (first 8 HELLO payload
               bytes), persisted in memory for the server's lifetime;
               power byte = 1 iff brightness > 0

Usage:
    python server.py --port N
"""

from __future__ import annotations

import argparse
import asyncio
import os
import struct
import sys
import time

# ---------------------------------------------------------------------------
# Protocol constants (recovered spec)
# ---------------------------------------------------------------------------

PREFIX = bytes.fromhex("4c4d02")           # b'LM\x02'
HEADER_LEN = 8                             # prefix(3) + type(1) + seq(2) + len(2)
CRC_LEN = 2
FRAME_OVERHEAD = HEADER_LEN + CRC_LEN      # empty-payload frame = 10 bytes

TYPE_HELLO = 0x01
TYPE_CHALLENGE = 0x81
TYPE_AUTH = 0x02
TYPE_AUTH_OK = 0x82
TYPE_GET_STATUS = 0x03
TYPE_STATUS = 0x83
TYPE_SET_BRIGHTNESS = 0x04
TYPE_SET_COLOR = 0x05
TYPE_ACK = 0x90
TYPE_ERROR = 0xEE

ERROR_CLASS = 0x03                         # rejection class observed in captures

AUTH_XOR = 0x5A
NONCE_LEN = 4
DEVICE_ID_LEN = 8

BRIGHTNESS_MAX = 100
DEFAULT_BRIGHTNESS = 0x64                  # 100
DEFAULT_COLOR = b"\xff\xff\xff"

# Payload sizes the client is allowed to send, keyed by request type.
CLIENT_PAYLOAD_SIZES = {
    TYPE_HELLO: 10,
    TYPE_AUTH: NONCE_LEN,
    TYPE_GET_STATUS: 0,
    TYPE_SET_BRIGHTNESS: 1,
    TYPE_SET_COLOR: 3,
}


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------

def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, xorout 0."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def build_frame(msg_type: int, seq: int, payload: bytes) -> bytes:
    """Assemble one protocol frame with a valid trailing CRC."""
    frame = bytearray(PREFIX)
    frame.append(msg_type & 0xFF)
    frame += struct.pack("<H", seq & 0xFFFF)
    frame += struct.pack("<H", len(payload))
    frame += payload
    frame += struct.pack("<H", crc16_ccitt_false(bytes(frame[2:])))
    return bytes(frame)


# ---------------------------------------------------------------------------
# Lamp state (per device id, persists for the server's lifetime)
# ---------------------------------------------------------------------------

class LampState:
    """Persisted lamp state for one device id."""

    __slots__ = ("brightness", "color")

    def __init__(self) -> None:
        self.brightness: int = DEFAULT_BRIGHTNESS
        self.color: bytes = DEFAULT_COLOR

    @property
    def power(self) -> int:
        return 1 if self.brightness > 0 else 0

    def status_payload(self) -> bytes:
        """STATUS payload: power, brightness, R, G, B (5 bytes)."""
        return bytes((self.power, self.brightness, *self.color))


# ---------------------------------------------------------------------------
# Per-connection session
# ---------------------------------------------------------------------------

class ClientSession:
    """One TCP client: framing, handshake and command dispatch."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        devices: dict[bytes, LampState],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._devices = devices          # shared device-id -> state map
        self._seq = 1                    # server -> client counter, starts at 1
        self._device_id: bytes | None = None
        self._nonce: bytes | None = None
        self._authenticated = False
        self._buffer = bytearray()

    # -- lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        peer = self._writer.get_extra_info("peername")
        print(f"connection from {peer}", file=sys.stderr, flush=True)
        try:
            while True:
                data = await self._reader.read(4096)
                if not data:
                    break                # clean disconnect
                self._buffer.extend(data)
                await self._process_buffer()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass                         # client vanished: never crash on it
        finally:
            await self._close()
            print(f"connection closed ({peer})", file=sys.stderr, flush=True)

    async def _close(self) -> None:
        try:
            if not self._writer.is_closing():
                self._writer.close()
            await self._writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    # -- framing --------------------------------------------------------------

    async def _process_buffer(self) -> None:
        while True:
            # Re-synchronize on the frame prefix if the stream ever desyncs.
            idx = self._buffer.find(PREFIX)
            if idx == -1:
                # No full prefix present; keep only bytes that could start one.
                if len(self._buffer) > len(PREFIX) - 1:
                    del self._buffer[: len(self._buffer) - (len(PREFIX) - 1)]
                return
            if idx > 0:
                del self._buffer[:idx]
            if len(self._buffer) < FRAME_OVERHEAD:
                return                  # wait for header + CRC
            (payload_len,) = struct.unpack_from("<H", self._buffer, 6)
            frame_len = FRAME_OVERHEAD + payload_len
            if len(self._buffer) < frame_len:
                return                  # wait for the rest of the frame
            frame = bytes(self._buffer[:frame_len])
            del self._buffer[:frame_len]

            try:
                await self._handle_frame(frame)
            except OSError:
                raise                   # connection-level failure: bubble up
            except Exception as exc:    # keep serving no matter what
                print(f"dropped malformed frame: {exc!r}",
                      file=sys.stderr, flush=True)

    # -- dispatch -------------------------------------------------------------

    async def _handle_frame(self, frame: bytes) -> None:
        msg_type = frame[3]
        (req_seq,) = struct.unpack_from("<H", frame, 4)
        (payload_len,) = struct.unpack_from("<H", frame, 6)
        payload = frame[HEADER_LEN:HEADER_LEN + payload_len]

        # CRC covers bytes [2 : 8 + payload_len], stored little-endian at the end.
        (crc_received,) = struct.unpack_from("<H", frame, HEADER_LEN + payload_len)
        if crc16_ccitt_false(frame[2:HEADER_LEN + payload_len]) != crc_received:
            return                      # corrupt frame: silently ignore

        expected_size = CLIENT_PAYLOAD_SIZES.get(msg_type)
        if expected_size is None or len(payload) != expected_size:
            await self._send_error(req_seq)
            return

        if msg_type == TYPE_HELLO:
            self._device_id = bytes(payload[:DEVICE_ID_LEN])
            self._nonce = os.urandom(NONCE_LEN)
            self._authenticated = False
            await self._send(TYPE_CHALLENGE, self._nonce)
            return

        if msg_type == TYPE_AUTH:
            if self._nonce is not None and bytes(payload) == self._expected_auth():
                self._authenticated = True
                body = struct.pack(
                    "<HI",
                    int.from_bytes(os.urandom(2), "little"),   # session id
                    int(time.time()) & 0xFFFFFFFF,             # unix time u32 LE
                )
                await self._send(TYPE_AUTH_OK, body)
            else:
                await self._send_error(req_seq)
            return

        if not self._authenticated or self._device_id is None:
            await self._send_error(req_seq)
            return

        state = self._devices.setdefault(self._device_id, LampState())

        if msg_type == TYPE_GET_STATUS:
            await self._send(TYPE_STATUS, state.status_payload())

        elif msg_type == TYPE_SET_BRIGHTNESS:
            value = payload[0]
            if value > BRIGHTNESS_MAX:
                await self._send_error(req_seq)
                return
            state.brightness = value       # power derives from brightness > 0
            await self._send_ack(req_seq, msg_type)

        elif msg_type == TYPE_SET_COLOR:
            state.color = bytes(payload)
            await self._send_ack(req_seq, msg_type)

    def _expected_auth(self) -> bytes:
        """Expected AUTH payload: reversed nonce, each byte XOR 0x5A."""
        assert self._nonce is not None
        return bytes(b ^ AUTH_XOR for b in reversed(self._nonce))

    # -- send helpers -----------------------------------------------------------

    async def _send_ack(self, req_seq: int, req_type: int) -> None:
        """ACK payload = request seq (u16 LE) + request type (u8)."""
        await self._send(TYPE_ACK, struct.pack("<HB", req_seq, req_type))

    async def _send_error(self, req_seq: int) -> None:
        """ERROR payload = error class (u8) + request seq (u16 LE)."""
        await self._send(TYPE_ERROR, struct.pack("<BH", ERROR_CLASS, req_seq))

    async def _send(self, msg_type: int, payload: bytes) -> None:
        frame = build_frame(msg_type, self._seq, payload)
        self._seq += 1                   # +1 per frame sent, per connection
        if self._seq > 0xFFFF:
            self._seq = 1
        self._writer.write(frame)
        await self._writer.drain()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def serve(host: str, port: int) -> None:
    devices: dict[bytes, LampState] = {}  # lives for the whole server process

    async def on_client(reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> None:
        await ClientSession(reader, writer, devices).run()

    server = await asyncio.start_server(on_client, host, port)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets or ())
    print(f"Lumio cloud server listening on {addrs}", file=sys.stderr, flush=True)
    async with server:
        await server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replacement cloud server for the Lumio smart lamp."
    )
    parser.add_argument("--port", type=int, default=9000,
                        help="TCP port to listen on (default: 9000)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to bind (default: 127.0.0.1)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        pass
