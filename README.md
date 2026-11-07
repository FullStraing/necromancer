# Necromancer 🪦💡

> **Every connected device is one bankruptcy away from e-waste.**

Lumio (a fictional smart-lamp vendor) went bankrupt and shut down its cloud. The lamp's app now prints
`❌ Lumio: cannot reach Lumio Cloud`. **Necromancer** is an agent that recovers the dead cloud protocol from
incomplete evidence, **proves** each claim against the *unmodified original client*, and writes a replacement cloud.
At the end the original app controls the lamp again.

Built solo on 2026-11-07 at the AIE Code Summit Hackathon. Track: **Software Archaeology** + **Fetch.ai, Agents That Prove Their Work**.

## Evidence (what the agent gets)
| Evidence | File | Notes |
|---|---|---|
| Recorded traffic | `evidence/traffic.jsonl` | 246 TCP chunks from 28 app↔cloud sessions (own recording proxy, `tools/proxy.py`) |
| Vendor manual | `evidence/manual.md` | partial, with **3 planted errors** |
| Original app | `evidence/client/lumio_app.pyz` | bytecode only; used **only as a black-box oracle** (run, read verdict) |

Ground truth (original server, client and protocol sources, plus the answer key) is **sealed**: `ENVELOPE.sha256` was
committed in the first commit, and the sources are revealed only at the end (`tools/reveal.py` checks the hashes and scores the agent).

## How it works
```
traffic + manual ──► deterministic detectors ──► ✅ verified layout (zero counterexamples over all packets)
                         │ ambiguity kept as ❓ (e.g. two length-field candidates fit the traffic)
manual ──► Meta extracts claims ──► checked against traffic ──► ⚠️ "manual lies" with packet numbers
spec ──► Meta proposes semantic hypotheses ──► SubQ scores each over ALL evidence (long context) ──► 🎲 p
experiment library ──► SubQ picks next ──► mutated server ↔ ORIGINAL app ──► ✅/❌ by the oracle
spec + journal ──► Meta writes server.py ──► original app runs conformance scripts ──► repair loop ──► 💡
```

* **Observed vs inferred, separately:** every journal entry is `verified` (holds on every packet or confirmed by the
  original client), `inferred` (SubQ probability), `refuted` (counterexample with packet numbers or an oracle run), or `open`.
  The journal is append-only and versioned (`runs/<id>/journal.jsonl`).
* **The client is the oracle.** Experiments serve deliberately *wrong* answers to the real app: e.g. sequence numbers ≥ 0x0101
  break the tie between "length = u16 LE @6" and "length = u16 BE @5" (both fit every recorded packet); serving the
  manual's ACK code `0x80` makes the real app fail, so the manual is proven wrong by behavior as well as by traffic.
* **Behavioral equivalence:** the generated server must make the original app pass 5 conformance scripts
  (state persistence, power-off at brightness 0, out-of-range rejection, colors).

### Model roles
| Model | Role |
|---|---|
| **SubQ Snap 1.1** (decision model, no text generation) | `noul` probability for each semantic hypothesis, `choice` for the power rule and for **which experiment to run next**, all with the full evidence dump (every packet in hex + manual) as `state` |
| **Meta Muse Spark 1.3** or **ASI1** (Fetch.ai; used in the demo — same OpenAI-compatible client, `necromancer/llm.py`) | extracts manual claims, proposes hypotheses, **writes the replacement server** and repairs it from the client's error messages |
| Deterministic code | CRC catalog brute force, length/counter/echo detectors, auth-transform search, range thresholds (`necromancer/detectors.py`) |

Every model call has a deterministic fallback, so a failed tool call degrades the run instead of killing it.

### SubQ ablation: what long context does and doesn't buy
`uv run python -m necromancer.ablation` asks SubQ Snap 1.1 the same 18 typed questions under different evidence budgets
and scores them against the sealed answer key (`results/ablation.json`). The (lying) manual is always in context.

| SubQ `state` | packets | accuracy | mean p(true) | manual traps (4) | computed facts (4) |
|---|---|---|---|---|---|
| manual only | 0 | 56 % | 0.54 | **0/4** | 0/4 |
| 10 % of sessions | 22 | 72 % | 0.69 | 2/4 | 1/4 |
| 25 % of sessions | 62 | 67 % | 0.66 | 2/4 | 2/4 |
| full capture | 246 | 61 % | 0.61 | 2/4 | 1/4 |
| **full capture + verified detector facts** | 246 | **100 %** | **0.94** | **4/4** | **4/4** |

Honest reading:
* With **no traffic**, SubQ believes the manual (0/4 on planted errors). With traffic it starts overriding it.
* On **raw hex**, more context does *not* raise accuracy: arithmetic relations (CRC coverage, XOR transform, range
  threshold, counter start) are out of reach of reading alone, at any context size.
* That is exactly the split Necromancer uses: deterministic detectors compute, SubQ **weighs** verified facts against the
  manual and semantic hypotheses over everything at once. In that configuration it is 18/18. (Caveat: some detector facts
  nearly state the answers, so this row measures evidence *integration* and resisting a lying manual, not raw discovery.)
* In the live pipeline SubQ also makes mistakes that the oracle catches: it picked power rule `constant_on` (p=0.83);
  the original client refuted it ("lamp state mismatch on power") and the journal records the refutation.

## Fetch.ai agent (ASI:One)
`agent/asi_agent.py` is a uAgent with the **Agent Chat Protocol** and **ASI:One Interactive Cards**:
1. "My Lumio lamp is bricked" → **case-file card** (live check: the original app fails against the dead cloud)
2. "Resurrect" → live progress messages (manual lies, experiments, conformance) → **results card**
3. Card actions: *Show proof journal*, *Show manual lies*, *Get server code*

## Run it
```bash
uv sync
cp .env.example .env    # SUBQ_API_KEY, MODEL_API_KEY (Meta), AGENT_SEED
uv run python evidence/client/lumio_app.pyz status          # dead: cannot reach Lumio Cloud
uv run python -m necromancer.cli --serve                    # resurrect + keep serving on :7070
uv run python evidence/client/lumio_app.pyz brightness=70 color=ff8800 status   # 💡 alive again
uv run pytest -q
uv run python -m agent.asi_agent                            # Fetch.ai agent (connect the mailbox via the inspector link)
```

## Honest framing
This is a **controlled benchmark**: I wrote the dead device today, so the ground truth exists. That's what makes the
reconstruction *scorable*. To keep it honest, the sources are sealed by hash in the first commit, the app is bytecode-only
and used only as a black box, and the protocol is new (not something a model could remember).

## Prior work
Humphries, *You Bought It, They Bricked It* (2026), names trace coverage, behavioral oracles and experiment selection as open
problems; Necromancer targets the last two. de Ruiter & Poll, *Protocol State Fuzzing of TLS* (USENIX Sec 2015).
