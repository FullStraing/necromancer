"""LumaLink v2 wire protocol (SEALED ground truth — revealed only at the end).

Frame layout:
    magic   2  b"LM"
    version 1  0x02
    type    1
    seq     2  u16 little-endian (per-direction counter, starts at 1)
    length  2  u16 little-endian (payload length)
    payload N
    crc     2  CRC-16/CCITT-FALSE over version..payload (magic excluded), little-endian
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"LM"
VERSION = 0x02
HEADER = struct.Struct("<2sBBHH")

HELLO, AUTH, GET_STATUS, SET_BRIGHTNESS, SET_COLOR = 0x01, 0x02, 0x03, 0x04, 0x05
CHALLENGE, AUTH_OK, STATUS, ACK, ERROR = 0x81, 0x82, 0x83, 0x90, 0xEE

ERR_BAD_CRC, ERR_AUTH, ERR_RANGE, ERR_UNKNOWN = 0x01, 0x02, 0x03, 0x04


class ProtocolError(Exception):
    pass


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


@dataclass(frozen=True)
class Frame:
    type: int
    seq: int
    payload: bytes


def encode(frame: Frame) -> bytes:
    body = HEADER.pack(MAGIC, VERSION, frame.type, frame.seq, len(frame.payload)) + frame.payload
    return body + struct.pack("<H", crc16_ccitt_false(body[2:]))


def auth_token(nonce: bytes) -> bytes:
    return bytes(b ^ 0x5A for b in reversed(nonce))


async def read_frame(reader) -> Frame:
    head = await reader.readexactly(HEADER.size)
    magic, version, ftype, seq, length = HEADER.unpack(head)
    if magic != MAGIC or version != VERSION:
        raise ProtocolError("bad frame magic/version")
    rest = await reader.readexactly(length + 2)
    payload, crc_bytes = rest[:length], rest[length:]
    (crc,) = struct.unpack("<H", crc_bytes)
    if crc != crc16_ccitt_false(head[2:] + payload):
        raise ProtocolError("checksum error")
    return Frame(ftype, seq, payload)
