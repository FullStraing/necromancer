"""Terminal demo: `uv run python -m necromancer.cli [--serve]`"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel

from .pipeline import resurrect

STYLE = {"stage": "bold magenta", "info": "cyan", "warn": "yellow", "check": "green"}


async def main(serve: bool) -> int:
    con = Console()
    con.print(Panel.fit("🪦  NECROMANCER — resurrecting the Lumio cloud\n"
                        "Every connected device is one bankruptcy away from e-waste.", style="bold"))

    async def emit(kind: str, text: str) -> None:
        if kind == "entry":
            style = "red" if "LIES" in text or text.startswith("❌") else ("yellow" if text.startswith(("🎲", "❓")) else "")
            con.print(f"   {text}", style=style, highlight=False)
        else:
            con.print(("\n" if kind == "stage" else "   ") + text, style=STYLE.get(kind, ""), highlight=False)

    report = await resurrect(emit)
    con.print(Panel(report.summary(), title="Resurrection report", style="bold green"))
    con.print(f"Journal: {report.run_dir / 'journal.jsonl'}\nServer:  {report.synth.path if report.synth else '-'}")
    if serve and report.synth:
        con.print("\n[bold]Serving the resurrected cloud on :7070 — run the original app in another terminal:[/]\n"
                  "  python evidence/client/lumio_app.pyz brightness=70 color=ff8800 status")
        subprocess.run([sys.executable, str(report.synth.path), "--port", "7070"])
    return 0 if report.synth and report.synth.passed == len(report.synth.results) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help="keep the resurrected server running on :7070")
    sys.exit(asyncio.run(main(ap.parse_args().serve)))
