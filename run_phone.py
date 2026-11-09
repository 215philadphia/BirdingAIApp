"""Start the app and give it a temporary https:// address for your phone.

    python run_phone.py

Runs the web server on this computer, opens a free Cloudflare "quick tunnel"
to it, and prints the https:// address plus a QR code. Scan the code with the
iPhone camera to open the app in Safari. Press Ctrl+C to stop both.

Needs `cloudflared`. On a Mac: `brew install cloudflared`; on Windows:
`winget install --id Cloudflare.cloudflared`. Other systems:
https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def install_hint() -> str:
    system = platform.system()
    if system == "Darwin":
        return "brew install cloudflared"
    if system == "Windows":
        return "winget install --id Cloudflare.cloudflared"
    return (
        "see https://developers.cloudflare.com/cloudflare-one/connections/"
        "connect-networks/downloads/"
    )


def wait_for_server(port: int, server: subprocess.Popen, timeout: float = 120) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def find_tunnel_url(tunnel: subprocess.Popen, timeout: float = 60) -> str | None:
    """cloudflared prints the public address in its log output."""
    found: list[str] = []

    def read() -> None:
        assert tunnel.stdout is not None
        for line in tunnel.stdout:
            if os.environ.get("BIRDING_DEBUG"):
                print(line, end="")
            match = TUNNEL_URL_RE.search(line)
            if match and not found:
                found.append(match.group(0))

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not found and tunnel.poll() is None:
        time.sleep(0.2)
    return found[0] if found else None


def print_qr(url: str) -> None:
    try:
        import segno
    except ImportError:
        return
    segno.make(url, error="m").terminal(compact=True, border=2)


def stop(*procs: subprocess.Popen) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    port = int(os.environ.get("PORT", "8000"))
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        print("cloudflared is not installed. Install it with:\n")
        print(f"    {install_hint()}\n")
        print("then run this again.")
        return 1

    server_cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(port), "--proxy-headers",
    ]
    if (ROOT / ".env").is_file():
        server_cmd += ["--env-file", ".env"]

    print("Starting Birding AI (the first start downloads the BirdNET models, ~120 MB)…")
    server = subprocess.Popen(server_cmd, cwd=ROOT)
    if not wait_for_server(port, server):
        print("The server did not start; see the messages above.")
        stop(server)
        return 1

    print("Opening a secure tunnel…")
    tunnel = subprocess.Popen(
        [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = find_tunnel_url(tunnel)
    if not url:
        print("Could not open the tunnel. Run with BIRDING_DEBUG=1 to see cloudflared's output.")
        stop(tunnel, server)
        return 1

    print("\n" + "=" * 60)
    print("  Open this on your iPhone (or scan the QR code with the Camera):\n")
    print(f"  {url}\n")
    print_qr(url)
    print("  Tip: in Safari tap Share → Add to Home Screen.")
    print("  The address changes every time you run this. Press Ctrl+C to stop.")
    print("=" * 60 + "\n")

    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    try:
        while not stopping.is_set() and server.poll() is None and tunnel.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print("\nStopping…")
    stop(tunnel, server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
