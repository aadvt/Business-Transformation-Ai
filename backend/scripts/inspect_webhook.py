"""Print the latest stored Bolna payload as flattened key paths."""
from app.db.models import CallSession
from app.db.session import SessionLocal

def flatten(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items(): yield from flatten(item, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        for index, item in enumerate(value): yield from flatten(item, f"{prefix}[{index}]")
    else: yield prefix, value

with SessionLocal() as session:
    row = session.query(CallSession).filter(CallSession.webhook_raw.is_not(None)).order_by(CallSession.webhook_received_at.desc()).first()
    if row is None: raise SystemExit("No webhook_raw row found")
    print(f"call_id={row.id} execution_id={row.bolna_execution_id}")
    for path, value in flatten(row.webhook_raw): print(f"{path} = {value!r}")
