"""Offline-friendly D7 readiness checklist."""
import os
import socket
from pathlib import Path

def check(name, fn):
    try: print(f"PASS  {name}: {fn()}")
    except Exception as exc: print(f"FAIL  {name}: {exc}")

check("replay fixture", lambda: Path("fixtures/bolna_replay.json").exists())
check("backend health", lambda: socket.create_connection(("127.0.0.1", 8000), 2) and "port 8000 open")
public = os.getenv("BOLNA_WEBHOOK_PUBLIC_URL", "https://affecting-gains-thinner.ngrok-free.dev")
print(f"Webhook URL: {public}/api/v1/webhooks/bolna")
