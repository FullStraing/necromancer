# Lumio Smart Lamp — LumaLink Integration Notes (rev. C, partial)

*Recovered from a cached copy of the Lumio developer portal. Pages 3–7 are missing.*

## Frame format

Every LumaLink message is a single frame:

| Bytes | Field    | Notes |
|-------|----------|-------|
| 2     | magic    | ASCII `LM` |
| 1     | version  | protocol version, currently 2 |
| 1     | type     | message type, see below |
| 2     | seq      | sequence number |
| 2     | length   | payload length, **big-endian** |
| N     | payload  | |
| 2     | checksum | CRC-16 over the **entire frame** (magic through payload) |

## Message types

| Type | Name           | Direction | Payload |
|------|----------------|-----------|---------|
| 0x01 | HELLO          | app → cloud | device id (8) + firmware version (2) |
| 0x81 | CHALLENGE      | cloud → app | nonce (4) |
| 0x02 | AUTH           | app → cloud | response to nonce (4) |
| 0x82 | AUTH_OK        | cloud → app | session info |
| 0x03 | GET_STATUS     | app → cloud | — |
| 0x83 | STATUS         | cloud → app | lamp state |
| 0x04 | SET_BRIGHTNESS | app → cloud | level (1) |
| 0x05 | SET_COLOR      | app → cloud | R, G, B (3) |
| 0x80 | ACK            | cloud → app | acknowledges a command |

The app must complete HELLO/AUTH before sending commands. On any error the cloud replies with an
error frame (see page 5).
