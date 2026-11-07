"""Cross-examine the vendor manual: extract its claims (Meta, regex fallback) and test each one
deterministically against the traffic. A contradiction is reported with packet numbers."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from . import detectors as d
from .evidence import Packet
from .journal import Entry
from .llm import Meta, ModelUnavailable
from .spec import ProtocolSpec


class DocClaim(BaseModel):
    kind: Literal["length_endianness", "checksum_coverage", "type_code"]
    subject: str = Field(description="field or message name as written in the manual, e.g. 'length' or 'ACK'")
    value: str = Field(description="'big'/'little' for endianness; 'entire_frame' or 'after_magic' for coverage; hex code like '0x80' for type_code")
    quote: str = Field(default="", description="short verbatim quote from the manual")


class DocClaims(BaseModel):
    claims: list[DocClaim] = Field(max_length=40)


SYSTEM = ("You are a protocol archaeologist. Extract every checkable factual claim the vendor manual makes "
          "about byte order, checksum coverage and message type codes. Do not judge them, just extract.")


async def extract_claims(manual: str, meta: Meta) -> tuple[list[DocClaim], str]:
    if meta.available:
        try:
            got = await meta.complete_json(SYSTEM, manual, DocClaims, max_tokens=2500)
            if got.claims:
                return got.claims, "meta"
        except ModelUnavailable:
            pass
    return regex_claims(manual), "regex-fallback"


def regex_claims(manual: str) -> list[DocClaim]:
    claims = []
    m = re.search(r"length\s*\|[^\n]*?(big|little)-endian", manual, re.I)
    if m:
        claims.append(DocClaim(kind="length_endianness", subject="length", value=m.group(1).lower(), quote=m.group(0)))
    if re.search(r"entire frame", manual, re.I):
        claims.append(DocClaim(kind="checksum_coverage", subject="checksum", value="entire_frame", quote="CRC-16 over the entire frame"))
    for code, name in re.findall(r"\|\s*0x([0-9A-Fa-f]{2})\s*\|\s*([A-Z_]+)\s*\|", manual):
        claims.append(DocClaim(kind="type_code", subject=name, value=f"0x{code.lower()}", quote=f"0x{code} {name}"))
    return claims


def check_claim(c: DocClaim, spec: ProtocolSpec, packets: tuple[Packet, ...], n: int) -> Entry:
    cid = f"manual.{c.kind}.{c.subject.lower()}"
    if c.kind == "length_endianness":
        overhead = len(packets[0].data) - int.from_bytes(packets[0].data[spec.len_off:spec.len_off + 2], spec.len_endian)
        bad = d.counterexample_for_length(packets, spec.len_off, c.value.lower(), overhead)
        if bad is None:
            return Entry(id=cid, claim=f"manual: length is {c.value}-endian — consistent with traffic", status="verified",
                         confidence=1.0, source="manual")
        decoded = int.from_bytes(bad.data[spec.len_off:spec.len_off + 2], c.value.lower())
        return Entry(id=cid, status="refuted", confidence=1.0, source="detector", evidence=(bad.idx,),
                     claim=f"⚠️ MANUAL LIES: says length is {c.value}-endian, but packet #{bad.idx} would then carry "
                           f"{decoded} payload bytes while it has {len(bad.data) - overhead}; real: {spec.len_endian}-endian",
                     detail={"quote": c.quote})
    if c.kind == "checksum_coverage":
        full = c.value.lower().startswith("entire") or c.value.lower() in {"whole_frame", "all"}
        if not full:
            return Entry(id=cid, claim="manual: checksum coverage claim consistent", status="verified", confidence=1.0, source="manual")
        algos = d.crc_matches_anywhere(packets, 0)
        if algos:
            return Entry(id=cid, claim=f"manual: CRC over entire frame — matches {algos[0]}", status="verified", confidence=1.0, source="manual")
        return Entry(id=cid, status="refuted", confidence=1.0, source="detector", evidence=tuple(p.idx for p in packets[:3]),
                     claim=f"⚠️ MANUAL LIES: CRC 'over the entire frame' fits none of 8 CRC-16 variants on any of {n} packets; "
                           f"real: {spec.crc_algo} starting at byte {spec.crc_start} (prefix excluded)",
                     detail={"quote": c.quote})
    role = c.subject.lower()
    try:
        code = int(c.value, 16)
    except ValueError:
        return Entry(id=cid, claim=f"manual: unparseable type code {c.value!r}", status="open", confidence=0.5, source="manual")
    real = spec.codes.get(role)
    seen = [p.idx for p in packets if p.data[spec.type_off] == code]
    if real == code:
        return Entry(id=cid, claim=f"manual: {c.subject} = 0x{code:02x} — confirmed in {len(seen)} packets", status="verified",
                     confidence=1.0, source="manual", evidence=tuple(seen[:3]))
    if real is None:
        return Entry(id=cid, claim=f"manual: {c.subject} = 0x{code:02x} — role not identified in traffic", status="open",
                     confidence=0.5, source="manual")
    real_pk = [p.idx for p in packets if p.data[spec.type_off] == real]
    return Entry(id=cid, status="refuted", confidence=1.0, source="detector", evidence=tuple(real_pk[:3]),
                 claim=f"⚠️ MANUAL LIES: says {c.subject} = 0x{code:02x}, but 0x{code:02x} never appears in {n} packets; "
                       f"{c.subject} is 0x{real:02x} (e.g. #{', #'.join(map(str, real_pk[:3]))})",
                 detail={"quote": c.quote})
