"""Stage the 'archaeological site' from the sealed originals (run once, before the cloud 'dies').

1. Compile the original client to a bytecode-only zipapp  -> evidence/client/lumio_app.pyz
2. Run the original cloud server behind the recording proxy and replay ~28 user sessions
   -> evidence/traffic.jsonl
3. Write ENVELOPE.sha256 with hashes of every sealed source file.
"""
from __future__ import annotations

import hashlib
import py_compile
import random
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEALED = ROOT / "sealed"
EVIDENCE = ROOT / "evidence"
APP = EVIDENCE / "client" / "lumio_app.pyz"
TRAFFIC = EVIDENCE / "traffic.jsonl"


def build_app() -> None:
    APP.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(APP, "w", zipfile.ZIP_DEFLATED) as zf:
            for src, name in [(SEALED / "lumio_proto.py", "lumio_proto.pyc"),
                              (SEALED / "lumio_client.py", "lumio_client.pyc")]:
                out = Path(tmp) / name
                py_compile.compile(str(src), cfile=str(out), doraise=True)
                zf.write(out, name)
            main = Path(tmp) / "__main__.pyc"
            (Path(tmp) / "__main__.py").write_text("from lumio_client import main\nmain()\n")
            py_compile.compile(str(Path(tmp) / "__main__.py"), cfile=str(main), doraise=True)
            zf.write(main, "__main__.pyc")


def sessions(rng: random.Random) -> list[list[str]]:
    plans: list[list[str]] = [["status"], ["brightness=70", "status"], ["color=ff8800", "status"]]
    for _ in range(22):
        cmds = []
        for _ in range(rng.randint(1, 4)):
            pick = rng.random()
            if pick < 0.35:
                cmds.append("status")
            elif pick < 0.7:
                cmds.append(f"brightness={rng.randint(0, 100)}")
            else:
                cmds.append(f"color={rng.randbytes(3).hex()}")
        plans.append(cmds)
    # an old app build without client-side validation produced a few out-of-range requests
    plans += [["--legacy", "brightness=150", "status"], ["--legacy", "brightness=200"],
              ["--legacy", "brightness=101", "brightness=40", "status"]]
    return plans


def capture() -> None:
    TRAFFIC.unlink(missing_ok=True)
    py = sys.executable
    server = subprocess.Popen([py, str(SEALED / "lumio_server.py"), "--port", "7101"], cwd=SEALED)
    proxy = subprocess.Popen([py, str(ROOT / "tools" / "proxy.py"), "--listen", "7100",
                              "--upstream", "7101", "--out", str(TRAFFIC)])
    time.sleep(0.8)
    rng = random.Random(1107)
    devices = ["4c554d0000c0ffee", "4c554d00000badd1", "4c554d0000f00d42"]
    try:
        for plan in sessions(rng):
            dev = rng.choice(devices)
            subprocess.run([py, str(APP), "--port", "7100", "--device", dev, *plan],
                           check=False, capture_output=True, timeout=10)
            time.sleep(0.05)
    finally:
        proxy.terminate()
        server.terminate()


def envelope() -> None:
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  sealed/{p.name}"
             for p in sorted(SEALED.glob("*.py"))]
    (ROOT / "ENVELOPE.sha256").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    build_app()
    capture()
    envelope()
    print(f"app={APP} traffic={sum(1 for _ in TRAFFIC.open())} records")
