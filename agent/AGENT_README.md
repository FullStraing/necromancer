# Necromancer — resurrect bricked smart devices

![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)

**Every connected device is one bankruptcy away from e-waste.** When a vendor shuts down its cloud, devices become bricks.
Necromancer is a software-archaeology agent that brings the cloud back — and proves its work.

## What it does
1. Excavates the evidence: recorded app↔cloud traffic, a partial (and partly wrong) vendor manual, the original app.
2. Runs exhaustive deterministic detectors (CRC catalog, length/counter/echo fields, auth transform) — every ✅ holds on every packet.
3. Cross-examines the manual and proves its errors with packet numbers.
4. Meta Muse Spark proposes semantic hypotheses; SubQ Snap scores them over the whole evidence in long context (🎲 = probability).
5. Runs active experiments: serves deliberately mutated responses to the **original, unmodified app** (the oracle); SubQ picks the next experiment.
6. Meta writes the replacement cloud server; the original app must pass conformance scripts against it (repair loop on failures).

## How to use (ASI:One)
- “My Lumio lamp is bricked” → case-file card
- “Resurrect it” → live progress, then a results card
- “Show proof journal” · “Show manual lies” · “Get server code”

Source: https://github.com/FullStraing/necromancer
