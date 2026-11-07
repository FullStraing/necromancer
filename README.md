# Necromancer 🪦💡

> Every connected device is one bankruptcy away from e-waste.

Lumio (a fictional smart-lamp company) went bankrupt and shut down its cloud. The lamp's app now prints
`❌ Lumio: cannot reach Lumio Cloud`. Necromancer is an agent that recovers the dead cloud protocol from
incomplete evidence, proves its reconstruction against the **unmodified original client**, and resurrects
the cloud as a replacement server.

Work in progress — built today (2026-11-07) at the AIE Code Summit Hackathon.

## Sealed envelope

`ENVELOPE.sha256` holds the SHA-256 of the original server / client / protocol sources. They are **not** in the
repo until the reveal commit at the end, so you can verify the agent never saw the ground truth.

Evidence available to the agent (`evidence/`):
- `client/lumio_app.pyz` — the original app, bytecode only, used purely as a black-box oracle
- `traffic.jsonl` — recorded client↔cloud TCP chunks from 28 sessions
- `manual.md` — a partial developer doc (which may be wrong)
