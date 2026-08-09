import re
from dataclasses import dataclass
from difflib import SequenceMatcher

HEADER_TOKENS = {
    "vendor_master": {"vendor", "supplier", "gstin", "phone", "category"},
    "purchase_log": {"po", "purchase", "vendor", "sku", "quantity", "qty", "price"},
    "inventory": {"sku", "stock", "on hand", "on_hand", "reorder", "consumption"},
    "rate_card": {"sku", "item", "price", "rate", "lead time", "vendor"},
}

@dataclass
class ParsedSheet:
    name: str
    parser: str
    classification: str
    confidence: float
    headers: list[str]
    rows: list[dict]
    warnings: list[str]

def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())

def find_header_row(values: list[list], scan: int = 10) -> int:
    best = (0, 0)
    for index, row in enumerate(values[:scan]):
        cells = [_text(v) for v in row if _text(v)]
        non_numeric = sum(not re.fullmatch(r"[\d., -]+", cell) for cell in cells)
        distinct = len(set(cells))
        score = non_numeric * 3 + distinct
        if score > best[1]: best = (index, score)
    return best[0]

def classify_headers(headers: list[str]) -> tuple[str, float]:
    normalized = set(_text(h) for h in headers)
    scores = {kind: len(normalized & tokens) for kind, tokens in HEADER_TOKENS.items()}
    kind, score = max(scores.items(), key=lambda item: item[1])
    if score == 0: return "unknown", 0.0
    return kind, min(0.99, score / max(3, len(HEADER_TOKENS[kind])))

def parse_workbook(path: str, filename: str) -> list[ParsedSheet]:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for Excel ingest") from exc
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    result = []
    for sheet in workbook.worksheets:
        values = [list(row) for row in sheet.iter_rows(values_only=True)]
        header_index = find_header_row(values)
        headers = [_text(value) for value in values[header_index]]
        classification, confidence = classify_headers(headers)
        rows = []
        for values_row in values[header_index + 1:]:
            if not any(value not in (None, "") for value in values_row): continue
            rows.append({headers[index]: values_row[index] if index < len(values_row) else None for index in range(len(headers)) if headers[index]})
        result.append(ParsedSheet(sheet.title, "OPENPYXL", classification, confidence, headers, rows, []))
    return result

def normalize_vendor_name(name: str) -> str:
    value = _text(name)
    value = re.sub(r"\b(private limited|pvt ltd|pvt\. ltd|limited|ltd|& co|and company)\b", "", value)
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", value)).strip()

def _similarity(left: str, right: str) -> float:
    left_normalized, right_normalized = normalize_vendor_name(left), normalize_vendor_name(right)
    left_tokens, right_tokens = set(left_normalized.split()), set(right_normalized.split())
    left_acronym = "".join(token[0] for token in left_normalized.split() if token)
    right_acronym = "".join(token[0] for token in right_normalized.split() if token)
    if len(left_normalized.split()) == 2 and len(left_normalized.split()[0]) == 1: left_normalized = left_acronym
    if len(right_normalized.split()) == 2 and len(right_normalized.split()[0]) == 1: right_normalized = right_acronym
    if len(left_normalized) <= 5 and left_normalized == right_acronym[:len(left_normalized)]: return 0.78
    if len(right_normalized) <= 5 and right_normalized == left_acronym[:len(right_normalized)]: return 0.78
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if overlap: return overlap
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()

def resolve_vendor_names(records: list[dict], threshold: float = 0.72) -> dict:
    groups: list[list[dict]] = []
    for record in records:
        name = str(record.get("vendor_name") or record.get("vendor") or "").strip()
        if not name: continue
        gstin = str(record.get("gstin") or "").strip().upper()
        matched = None
        for group in groups:
            anchor = group[0]
            same_gstin = gstin and anchor.get("gstin") and gstin == anchor["gstin"]
            score = _similarity(name, anchor["name"])
            if same_gstin or score >= threshold:
                matched = group; break
        if matched is None: groups.append([{"name": name, "gstin": gstin}])
        else: matched.append({"name": name, "gstin": gstin})
    merged = [[item["name"] for item in group] for group in groups if len(group) > 1]
    return {"raw_count": len(records), "unique_count": len(groups), "merged_groups": merged, "groups": groups}
