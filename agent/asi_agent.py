"""Necromancer uAgent — Agent Chat Protocol + ASI:One Interactive Cards.

Run:  uv run python -m agent.asi_agent      (needs AGENT_SEED in .env; connect the mailbox via the printed inspector link)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from agent.cards import REPO, card_message, case_file, result_card, text_message  # noqa: E402
from agent.intents import parse_intent  # noqa: E402
from necromancer.evidence import load_manual, load_traffic, sessions  # noqa: E402
from necromancer.oracle import dead_cloud_check  # noqa: E402
from necromancer.pipeline import Report, resurrect  # noqa: E402

SEED = os.getenv("AGENT_SEED")
if not SEED:
    raise SystemExit("AGENT_SEED not configured in .env")

agent = Agent(
    name="necromancer",
    seed=SEED,
    port=int(os.getenv("AGENT_PORT", "8001")),
    mailbox=True,
    publish_agent_details=True,
    readme_path=str(ROOT / "agent" / "AGENT_README.md"),
    description=("Resurrects bricked smart devices whose vendor cloud died: recovers the protocol from traffic + docs, "
                 "proves every claim against the original client, and writes a replacement server."),
)
chat = Protocol(spec=chat_protocol_spec)
REPORTS: dict[str, Report] = {}
BUSY: set[str] = set()

async def send_case_file(ctx: Context, sender: str) -> None:
    packets = load_traffic()
    dead = await dead_cloud_check()
    status = f"❌ “{dead.error}”" if not dead.ok else "online?!"
    await ctx.send(sender, card_message(
        "🪦 Lumio went bankrupt and switched off its cloud — every Lumio lamp is now a brick. I can bring it back: "
        "I reconstruct the dead protocol from evidence, prove each claim against the original app, and write a new cloud.",
        "detail", case_file(len(packets), len(sessions(packets)), status)))


async def run_resurrection(ctx: Context, sender: str) -> None:
    if sender in BUSY:
        await ctx.send(sender, text_message("⏳ Already resurrecting — progress updates are on their way."))
        return
    BUSY.add(sender)
    buffer: list[str] = []

    async def flush() -> None:
        if buffer:
            await ctx.send(sender, text_message("\n".join(buffer)))
            buffer.clear()

    async def emit(kind: str, line: str) -> None:
        if kind == "stage":
            await flush()
            buffer.append(f"**{line}**")
        elif kind == "entry" and ("MANUAL LIES" in line or "🧪" in line or "AMBIGUOUS" in line or "bricked" in line or "🎲" in line):
            buffer.append(line)
        elif kind in ("info", "check", "warn"):
            buffer.append(line)

    try:
        report = await resurrect(emit)
        await flush()
        REPORTS[sender] = report
        await ctx.send(sender, card_message("Resurrection finished. Every ✅ is mechanically proven (all packets or the "
                                            "original client); every 🎲 is a SubQ probability, not a fact.",
                                            "detail", result_card(report)))
    except Exception as e:  # report any failure to the user instead of going silent
        ctx.logger.exception("resurrection failed")
        await flush()
        await ctx.send(sender, text_message(f"💀 Resurrection failed: {type(e).__name__}: {e}. Say “resurrect” to retry."))
    finally:
        BUSY.discard(sender)


async def send_followup(ctx: Context, sender: str, intent: str) -> None:
    report = REPORTS.get(sender)
    if report is None:
        await ctx.send(sender, text_message("No resurrection yet — say “resurrect” first."))
        return
    if intent == "journal":
        lines = [e.line() for e in report.journal.entries()]
        await ctx.send(sender, text_message("**Proof journal** (✅ verified · 🎲 inferred · ❌ refuted · ❓ open)\n\n"
                                            + "\n".join(f"- {ln}" for ln in lines)[:15000]))
    elif intent == "lies":
        await ctx.send(sender, text_message("**Where the vendor manual is wrong** (each proven by packets AND by the original app):\n\n"
                                            + "\n".join(f"- {e.claim}" for e in report.manual_lies)))
    elif intent == "code" and report.synth:
        code = report.synth.path.read_text()
        await ctx.send(sender, text_message(f"**Resurrected Lumio cloud** — run `python resurrected_server.py --port 7070` "
                                            f"and the original app works again. Source of the agent: {REPO}\n\n```python\n{code[:14000]}\n```"))


@chat.on_message(ChatMessage)
async def on_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    intent = parse_intent(text)
    ctx.logger.info(f"{sender[:16]}… intent={intent} text={text[:300]!r}")
    if intent == "resurrect":
        await run_resurrection(ctx, sender)
    elif intent == "evidence":
        packets, manual = load_traffic(), load_manual()
        sample = "\n".join(f"#{p.idx} s{p.session} {p.dir} {p.data.hex()}" for p in packets[:8])
        await ctx.send(sender, text_message(f"**Evidence** — {len(packets)} packets / {len(sessions(packets))} sessions.\n\n"
                                            f"```\n{sample}\n…\n```\n\n**Recovered manual:**\n\n{manual}\n\nSay “resurrect” to begin."))
    elif intent in ("journal", "lies", "code"):
        await send_followup(ctx, sender, intent)
    else:
        await send_case_file(ctx, sender)


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    return None


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
