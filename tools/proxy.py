"""Transparent TCP recording proxy: client <-> proxy <-> server, every chunk logged to JSONL.

Each line: {"session": int, "t": float, "dir": "c2s"|"s2c", "hex": str}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path


class Recorder:
    def __init__(self, path: Path):
        self.path = path
        self.session = 0
        self.t0 = time.monotonic()

    def next_session(self) -> int:
        self.session += 1
        return self.session

    def log(self, session: int, direction: str, data: bytes) -> None:
        rec = {"session": session, "t": round(time.monotonic() - self.t0, 4), "dir": direction, "hex": data.hex()}
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")


async def pump(reader, writer, rec: Recorder, session: int, direction: str) -> None:
    try:
        while data := await reader.read(65536):
            rec.log(session, direction, data)
            writer.write(data)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


async def run_proxy(listen: int, upstream: int, out: Path) -> None:
    rec = Recorder(out)

    async def on_conn(c_reader, c_writer):
        session = rec.next_session()
        try:
            s_reader, s_writer = await asyncio.open_connection("127.0.0.1", upstream)
        except OSError:
            c_writer.close()
            return
        await asyncio.gather(
            pump(c_reader, s_writer, rec, session, "c2s"),
            pump(s_reader, c_writer, rec, session, "s2c"),
        )

    server = await asyncio.start_server(on_conn, "127.0.0.1", listen)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=7000)
    ap.add_argument("--upstream", type=int, default=7001)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    asyncio.run(run_proxy(a.listen, a.upstream, a.out))
