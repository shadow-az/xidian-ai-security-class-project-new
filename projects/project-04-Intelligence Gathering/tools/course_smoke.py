"""Start the real local service, probe it, and stop only the child we created."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log = root / "data/course_smoke.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen([sys.executable, "start.py", "--port", str(port)],
                                   cwd=root, stdout=output, stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 45
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Service exited; inspect local data/course_smoke.log")
                try:
                    with opener.open(base + "/api/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Service startup timed out; inspect local log")
                    time.sleep(0.5)
            if health != {"status": "ok"}:
                raise RuntimeError("Unexpected health response")
            with opener.open(base + "/", timeout=5) as response:
                content_type = response.headers.get("Content-Type", "")
                body = response.read().decode("utf-8")
                if "text/html" not in content_type or "<html" not in body.lower():
                    raise RuntimeError("Bundled frontend HTML is unavailable")
            with opener.open(base + "/api/env/check", timeout=40) as response:
                environment = json.load(response)
            print(json.dumps({"health": health, "frontend_html": True,
                              "crawler_environment": environment.get("success", False),
                              "port": port}, indent=2))
            if not environment.get("success"):
                raise RuntimeError("Crawler environment check failed; run python main.py --help")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
