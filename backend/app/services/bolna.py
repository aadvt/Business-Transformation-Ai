"""Parser and deterministic validation for the observed Bolna Execution shape."""
import re
from datetime import datetime, timezone

FIELD_PATHS = {
    "availability_confirmed": ("extracted_data", "availability_confirmed"),
    "unit_price": ("extracted_data", "unit_price"),
    "quantity": ("extracted_data", "quantity"),
    "delivery_date": ("extracted_data", "delivery_date"),
    "payment_terms_days": ("extracted_data", "payment_terms_days"),
    "upi_id": ("extracted_data", "upi_id"),
    "gstin": ("extracted_data", "gstin"),
    "vendor_id": ("extracted_data", "vendor_id"),
}

class ParsedCall:
    def __init__(self, **values): self.__dict__.update(values)

def _get_path(payload, path):
    value = payload
    for part in path:
        if not isinstance(value, dict): return None
        value = value.get(part)
    return value

def _extract_value(payload, name):
    value = _get_path(payload, FIELD_PATHS[name])
    if value is not None: return value
    root = payload.get("extracted_data") or {}
    if isinstance(root, dict):
        for group in root.values():
            if isinstance(group, dict):
                for key, item in group.items():
                    if key.lower().replace(" ", "_") == name and isinstance(item, dict):
                        return item.get("subjective") or item.get("objective")
    return None

def parse_bolna_payload(raw: dict) -> ParsedCall:
    warnings, extracted, transcript = [], {}, []
    for name in FIELD_PATHS:
        value = _extract_value(raw, name)
        if value is None: warnings.append(f"missing:{name}")
        else: extracted[name] = value
    text = raw.get("transcript")
    if text:
        for seq, line in enumerate(str(text).splitlines()):
            speaker, separator, utterance = line.partition(":")
            transcript.append({"seq": seq, "speaker": speaker.strip().upper() if separator else "UNKNOWN", "text": utterance.strip() if separator else line.strip(), "at_offset_ms": None})
    else: warnings.append("missing:transcript")
    telephony = raw.get("telephony_data") or {}
    ended_at = raw.get("updated_at")
    return ParsedCall(execution_id=raw.get("id"), status=raw.get("status", "unknown"), transcript=transcript,
        extracted=extracted, phone=raw.get("user_number") or telephony.get("to_number"), warnings=warnings, ended_at=ended_at)

def validate_extracted(extracted: dict, guardrails: dict | None = None) -> dict:
    guardrails, result = guardrails or {}, {}
    availability = extracted.get("availability_confirmed")
    result["availability_confirmed"] = {"value": bool(availability) if availability is not None else None, "valid": availability is not None, **({"reason": "not discussed on the call"} if availability is None else {})}
    price = extracted.get("unit_price")
    try:
        paise = round(float(str(price).replace(",", "").replace("₹", "")) * 100)
        result["unit_price"] = {"value": paise, "valid": paise >= 0, "exceeds_guardrail": bool(guardrails.get("max_unit_price_paise") and paise > guardrails["max_unit_price_paise"])}
    except (TypeError, ValueError): result["unit_price"] = {"value": price, "valid": False, "reason": "missing or not a number"}
    quantity = extracted.get("quantity")
    try: result["quantity"] = {"value": int(quantity), "valid": int(quantity) > 0}
    except (TypeError, ValueError): result["quantity"] = {"value": quantity, "valid": False, "reason": "missing or must be a positive integer"}
    terms = extracted.get("payment_terms_days")
    try: result["payment_terms_days"] = {"value": int(terms), "valid": int(terms) >= 0}
    except (TypeError, ValueError): result["payment_terms_days"] = {"value": terms, "valid": False, "reason": "not discussed on the call"}
    upi = extracted.get("upi_id")
    upi_valid = upi is None or bool(re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+", str(upi)))
    result["upi_id"] = {"value": upi, "valid": upi_valid, **({"reason": "invalid UPI id"} if not upi_valid else {})}
    date_value = extracted.get("delivery_date")
    try:
        parsed = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)  # bare dates parse naive; comparing naive to aware raises
        result["delivery_date"] = {"value": date_value, "valid": parsed > datetime.now(timezone.utc)}
    except (TypeError, ValueError): result["delivery_date"] = {"value": date_value, "valid": False, "reason": "missing or invalid date"}
    gstin = extracted.get("gstin")
    result["gstin"] = {"value": gstin, "valid": gstin is None or bool(re.fullmatch(r"[0-9A-Z]{15}", str(gstin)))}
    return result
