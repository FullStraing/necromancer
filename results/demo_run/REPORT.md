# Necromancer run report

```
Journal: ✅ 34 verified · 🎲 22 inferred · ❌ 5 refuted · ❓ 0 open
Resurrected server (asi1, 1 round): original client passes 5/5 conformance scripts
Manual contradictions proven: 3 · Oracle experiments run: 12
Models: {'subq': 'subq-snap-1.1', 'meta': 'asi1'} · 207s
```

## Hypothesis journal

- ✅ Original client today: “cannot reach Lumio Cloud” — the lamp is bricked (oracle)
- ✅ every frame starts with constant bytes 4c4d02 (b'LM\x02') [pkts #1, #2, #3, #4, …] (detector)
- ✅ CRC-16/CCITT-FALSE over bytes [2:-2], stored little-endian in last 2 bytes [pkts #1, #2, #3, #4, …] (detector)
- ✅ byte 3 is a message-type code; app→cloud codes ['0x1', '0x2', '0x3', '0x4', '0x5'], cloud→app codes ['0x81', '0x82', '0x83', '0x90', '0xee'] (never overlap) [pkts #1, #2, #3, #4, …] (detector)
- ✅ u16 little-endian at offset 4 is a per-direction counter starting at 1, +1 per frame [pkts #1, #2, #3, #4, …] (detector)
- ✅ u16 little-endian at offset 6 = frame length − 10 [pkts #1, #2, #3, #4, …] (detector)
- ✅ STATUS payload[1:2] reflects the last accepted 0x04 value [pkts #14, #150, #172, #174, …] (detector)
- ✅ STATUS payload[2:5] reflects the last accepted 0x05 value [pkts #22, #62, #86, #122, …] (detector)
- ✅ type 0x90 payload[0:2] echoes the request's seq [pkts #12, #20, #28, #30, …] (detector)
- ✅ type 0x90 payload[2] echoes the request's type code [pkts #12, #20, #28, #30, …] (detector)
- ✅ type 0xee payload[1:3] echoes the request's seq [pkts #228, #236, #242] (detector)
- ✅ AUTH response = reversed nonce XOR 0x5a (holds for all 28 handshakes) [pkts #3, #9, #17, #25, …] (detector)
- ✅ 0x04 values ≤ 100 accepted, ≥ 101 rejected with 0xee [pkts #228, #236, #242] (detector)
- ❌ u16 big-endian at offset 5 = frame length − 10 — refuted: client accepted frames with seq ≥ 0x0101 [pkts #1, #2, #3] (oracle)
- ❌ ⚠️ MANUAL LIES: says length is big-endian, but packet #1 would then carry 2560 payload bytes while it has 10; real: little-endian [pkts #1] (detector)
- ❌ ⚠️ MANUAL LIES: CRC 'over the entire frame' fits none of 8 CRC-16 variants on any of 246 packets; real: CRC-16/CCITT-FALSE starting at byte 2 (prefix excluded) [pkts #1, #2, #3] (detector)
- ✅ manual: HELLO = 0x01 — confirmed in 28 packets [pkts #1, #7, #15] (manual)
- ✅ manual: CHALLENGE = 0x81 — confirmed in 28 packets [pkts #2, #8, #16] (manual)
- ✅ manual: AUTH = 0x02 — confirmed in 28 packets [pkts #3, #9, #17] (manual)
- ✅ manual: AUTH_OK = 0x82 — confirmed in 28 packets [pkts #4, #10, #18] (manual)
- ✅ manual: GET_STATUS = 0x03 — confirmed in 24 packets [pkts #5, #13, #21] (manual)
- ✅ manual: STATUS = 0x83 — confirmed in 24 packets [pkts #6, #14, #22] (manual)
- ✅ manual: SET_BRIGHTNESS = 0x04 — confirmed in 22 packets [pkts #11, #27, #29] (manual)
- ✅ manual: SET_COLOR = 0x05 — confirmed in 21 packets [pkts #19, #37, #39] (manual)
- ❌ ⚠️ MANUAL LIES: says ACK = 0x80, but 0x80 never appears in 246 packets; ACK is 0x90 (e.g. #12, #20, #28) [pkts #12, #20, #28] (detector)
- 🎲 Payload bytes 0-3 are ASCII 'LUM' plus NUL: a fixed-width, null-padded product/model name string rather than a binary field. p=0.98 (subq)
- 🎲 Bytes 5-7 with byte 4 as a zero high-pad form a 24-bit hexspeak build/model code (0BADD1, F00D42, C0FFEE) identifying the client firmware variant; constant per device, differs across units. p=0.92 (subq)
- 🎲 The same 4-byte group is a pre-shared handshake token the server validates and may mix into auth verification; explains why it is constant per device while differing between sessions s1-s5. p=0.95 (subq)
- 🎲 Bytes 8-9 (07 01) are a protocol version pair, major=7 minor=1, identical in every session. p=0.40 (subq)
- 🎲 Byte 8 is a capabilities bitmask (0x07 = brightness|color|status) and byte 9 a mode/flag byte (0x01 = default), not a version pair; falsify by finding a device with a value outside 0x00-0x07. p=0.80 (subq)
- 🎲 The 4 bytes are a fresh random per-session nonce: all 5 samples are distinct with high entropy and no monotonic trend; consumed exactly once by the auth reply. p=0.99 (subq)
- 🎲 The 4 bytes are a server timestamp or counter rather than RNG output; falsifiable since it must then be monotonic across sessions, but the samples look random, so this should lose to the nonce hypothesis. p=0.08 (subq)
- 🎲 Auth carries no secret: the response is fully determined by the challenge, so a captured (challenge, auth) pair replays successfully in a later session; testable by replay. p=0.99 (subq)
- 🎲 Server validation also depends on the hello magic, making the proof device-bound; falsify by replaying a correct auth after altering only the hello magic - acceptance kills this hypothesis and confirms unkeyed obfuscation. p=0.85 (subq)
- 🎲 Constant bytes 2-5 (0x0A91EF6A big-endian) are a server/firmware build or instance identifier, identical across all sessions and devices in the capture. p=0.98 (subq)
- 🎲 Constant bytes 2-5 are a little-endian epoch (0x6AEF910A, roughly Sept 2026); falsifiable because grants at different capture times must differ, yet every sample matches - expected to lose. p=0.04 (subq)
- 🎲 Constant bytes 2-5 are uptime in milliseconds (about 20.7 days if little-endian); falsifiable since it must grow between sessions and reset on reboot; constancy here argues against it. p=0.01 (subq)
- 🎲 Varying bytes 0-1 are a 16-bit little-endian session/ticket handle issued per login that the client must echo or reference in subsequent commands. p=0.58 (subq)
- 🎲 Varying bytes 0-1 are a 16-bit checksum of the accepted auth payload (sum, XOR-fold, or CRC-16 over the 4 auth bytes); directly testable by recomputation against the five sample pairs. p=0.33 (subq)
- 🎲 Status byte 0 (always 0x01) is a power/enable state enum where 1=on and 0=off, independent of brightness and color. p=0.99 (subq)
- 🎲 Status byte 0 is a mode selector or status-record version rather than power state; falsify by powering the device off and observing whether byte 0 actually changes. p=0.89 (subq)
- 🎲 Status byte 1 is the current/actual output level, which can lag the last requested value during fades; alternative framing: it always equals the last set_brightness. Test while a transition is in flight. p=0.78 (subq)
- 🎲 Error byte 0 (0x03) echoes the rejected command type (get_status=3), meaning these errors followed unauthenticated get_status attempts; byte 2 (0x00) is a subtype/detail field. p=0.62 (subq)
- 🎲 Byte 0 is the error-class enum (0x03 = not-authenticated or unknown-command) and byte 2 a per-class detail that is 0 for generic failures; competing framing with the echoed-type hypothesis. p=0.94 (subq)
- 🎲 Byte 2 (0x00) is the primary error code (0 = generic) while byte 0 carries context; distinguishable by triggering a different failure such as bad CRC and seeing byte 2 move while byte 0 stays 0x03. p=0.94 (subq)
- 🎲 The 3 payload bytes are R,G,B in that order (ff8800 renders orange); supported by status returning byte-identical color values. p=0.99 (subq)
- 🎲 The 3 bytes are B,G,R in LED hardware order, so ff8800 renders blue; falsify by sending ff8800 and observing the emitted hue. p=0.54 (subq)
- ❌ SubQ guessed power rule 'constant_on' (p=0.83) — REFUTED by the original client (“lamp state mismatch on power”) (oracle)
- ✅ 🧪 Traffic fits BOTH 'length = u16 LE @6' and 'length = u16 BE @5' (seq never exceeded 255). Which is real? → client accepts seq≥0x0101: length is u16 LE @6, BE@5 candidate refuted (oracle)
- ✅ 🧪 Does the client verify the checksum (and its byte order)? → checksum is verified with exact byte order (must implement) (client: “checksum error”) (oracle)
- ✅ 🧪 Does the client verify the ACK echoes the request seq? → ACK must echo request seq (must implement) (client: “ack does not match request”) (oracle)
- ✅ 🧪 Does the client verify the ACK echoes the request type? → ACK type echo is not checked by this client (implement anyway: observed in traffic) (oracle)
- ✅ 🧪 Does the client enforce server seq +1 per frame? → client enforces server seq increments (must implement) (client: “sequence error: replayed or out-of-order frame”) (oracle)
- ✅ 🧪 Serve the manual's ACK code 0x80 to the real client → real client rejects ACK=0x80 — manual is wrong (client: “unexpected reply type 0x80”) (oracle)
- ✅ 🧪 Is STATUS byte 0 really tied to brightness? Serve 'always on' after brightness=0 → client rejects 'always on' after brightness=0: power = (brightness > 0) confirmed (client: “lamp state mismatch on power”) (oracle)
- ✅ power = (brightness > 0) — confirmed by the original client (oracle)
- ✅ 🧪 Does the client interpret AUTH_OK session/timestamp bytes? → AUTH_OK contents are opaque to the client (any 6 bytes work) (oracle)
- ✅ 🧪 Must server seq start at 1? → client accepts any initial server seq (start value is cosmetic) (oracle)
- ✅ 🧪 Does the client cross-check STATUS against its own SETs? → server must persist lamp state (must implement) (client: “lamp state mismatch on brightness”) (oracle)
- ✅ 🧪 Serve the manual's whole-frame CRC to the real client → real client rejects the manual's CRC coverage — manual is wrong (client: “checksum error”) (oracle)
- ✅ 🧪 Serve the manual's big-endian length to the real client → real client rejects the manual's length encoding — manual is wrong (client: “cloud did not answer (timeout)”) (oracle)

## Conformance (original client vs resurrected server)

- ✅ `status brightness=37 color=12ab9f status` → {'power': True, 'brightness': 37, 'color': '12ab9f'}
- ✅ `brightness=0 status` → {'power': False, 'brightness': 0, 'color': '12ab9f'}
- ✅ `brightness=100 color=000000 status brightness=55 status` → {'power': True, 'brightness': 55, 'color': '000000'}
- ✅ `--legacy brightness=180 status` → {'power': True, 'brightness': 55, 'color': '000000'}
- ✅ `color=ffffff color=010203 status` → {'power': True, 'brightness': 55, 'color': '010203'}
