"""Lumio Cloud — the ORIGINAL vendor server (SEALED; "shut down" when Lumio went bankrupt)."""
from __future__ import annotations

import argparse
import asyncio
import os
import struct
import time

from lumio_proto import (
    ACK, AUTH, AUTH_OK, CHALLENGE, ERR_AUTH, ERR_BAD_CRC, ERR_RANGE, ERR_UNKNOWN, ERROR,
    GET_STATUS, HELLO, SET_BRIGHTNESS, SET_COLOR, STATUS, Frame, ProtocolError, auth_token,
    encode, read_frame,
)

DEFAULT_STATE = {"power": 1, "brightness": 100, "rgb": (255, 255, 255)}


class Session:
    def __init__(self, lamps: dict, writer: asyncio.StreamWriter):
        self.lamps = lamps
        self.writer = writer
        self.seq = 0
        self.nonce = b""
        self.device = b""
        self.authed = False

    async def send(self, ftype: int, payload: bytes) -> None:
        self.seq = (self.seq + 1) & 0xFFFF
        self.writer.write(encode(Frame(ftype, self.seq, payload)))
        await self.writer.drain()

    async def error(self, code: int, req_seq: int) -> None:
        await self.send(ERROR, struct.pack("<BH", code, req_seq))

    def state(self) -> dict:
        return self.lamps.setdefault(self.device, dict(DEFAULT_STATE))

    async def handle(self, f: Frame) -> bool:
        if f.type == HELLO:
            self.device = f.payload[:8]
            self.nonce = os.urandom(4)
            await self.send(CHALLENGE, self.nonce)
            return True
        if f.type == AUTH:
            if f.payload != auth_token(self.nonce):
                await self.error(ERR_AUTH, f.seq)
                return False
            self.authed = True
            sid = int.from_bytes(os.urandom(2), "little")
            await self.send(AUTH_OK, struct.pack("<HI", sid, int(time.time())))
            return True
        if not self.authed:
            await self.error(ERR_AUTH, f.seq)
            return False
        st = self.state()
        if f.type == GET_STATUS:
            await self.send(STATUS, bytes([st["power"], st["brightness"], *st["rgb"]]))
        elif f.type == SET_BRIGHTNESS:
            level = f.payload[0]
            if level > 100:
                await self.error(ERR_RANGE, f.seq)
                return True
            self.lamps[self.device] = {**st, "brightness": level, "power": int(level > 0)}
            await self.send(ACK, struct.pack("<HB", f.seq, f.type))
        elif f.type == SET_COLOR:
            self.lamps[self.device] = {**st, "rgb": tuple(f.payload[:3])}
            await self.send(ACK, struct.pack("<HB", f.seq, f.type))
        else:
            await self.error(ERR_UNKNOWN, f.seq)
        return True


async def serve(port: int) -> None:
    lamps: dict = {}

    async def on_conn(reader, writer):
        sess = Session(lamps, writer)
        try:
            while True:
                try:
                    frame = await read_frame(reader)
                except ProtocolError:
                    await sess.error(ERR_BAD_CRC, 0)
                    continue
                if not await sess.handle(frame):
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(on_conn, "127.0.0.1", port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7001)
    asyncio.run(serve(ap.parse_args().port))
