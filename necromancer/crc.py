"""Parametric CRC-16 catalog (Rocksoft model) used by the brute-force checksum detector."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Crc16:
    name: str
    poly: int
    init: int
    refin: bool
    refout: bool
    xorout: int

    def compute(self, data: bytes) -> int:
        crc = self.init
        for byte in data:
            b = _reflect8(byte) if self.refin else byte
            crc ^= b << 8
            for _ in range(8):
                crc = ((crc << 1) ^ self.poly) if crc & 0x8000 else (crc << 1)
                crc &= 0xFFFF
        if self.refout:
            crc = _reflect16(crc)
        return crc ^ self.xorout


def _reflect8(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


def _reflect16(v: int) -> int:
    return int(f"{v:016b}"[::-1], 2)


CATALOG: tuple[Crc16, ...] = (
    Crc16("CRC-16/CCITT-FALSE", 0x1021, 0xFFFF, False, False, 0x0000),
    Crc16("CRC-16/XMODEM", 0x1021, 0x0000, False, False, 0x0000),
    Crc16("CRC-16/KERMIT", 0x1021, 0x0000, True, True, 0x0000),
    Crc16("CRC-16/AUG-CCITT", 0x1021, 0x1D0F, False, False, 0x0000),
    Crc16("CRC-16/MODBUS", 0x8005, 0xFFFF, True, True, 0x0000),
    Crc16("CRC-16/ARC", 0x8005, 0x0000, True, True, 0x0000),
    Crc16("CRC-16/X-25", 0x1021, 0xFFFF, True, True, 0xFFFF),
    Crc16("CRC-16/BUYPASS", 0x8005, 0x0000, False, False, 0x0000),
)

BY_NAME = {c.name: c for c in CATALOG}
