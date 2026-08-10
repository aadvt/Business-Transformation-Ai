import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
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

def _sheet_from_values(name: str, parser: str, values: list[list]) -> ParsedSheet:
    header_index = find_header_row(values)
    headers = [_text(value) for value in values[header_index]]
    classification, confidence = classify_headers(headers)
    rows = []
    for values_row in values[header_index + 1:]:
        if not any(value not in (None, "") for value in values_row): continue
        rows.append({headers[index]: values_row[index] if index < len(values_row) else None for index in range(len(headers)) if headers[index]})
    return ParsedSheet(name, parser, classification, confidence, headers, rows, [])


# --- ROWS_FOUND preview payload -------------------------------------------------
#
# Caps on what a single ROWS_FOUND websocket frame may carry. The live feed keeps
# the last 50 events in an in-memory ring buffer and replays ALL of them to every
# client that connects (app/ws_manager.py), so an uncapped preview is paid for
# once per sheet AND again per reconnect. A 60-column sheet with free-text remark
# cells is an ordinary ERP export; without caps one frame is megabytes and a
# multi-sheet workbook fills the whole buffer with them. 8 rows x 120 chars keeps
# a frame in the tens of KB regardless of how messy the workbook is, which is all
# a "watch your data land" preview needs — the full parse is unaffected.
SAMPLE_ROW_LIMIT = 8
CELL_CHAR_LIMIT = 120


def _truncate(text: str) -> str:
    return text if len(text) <= CELL_CHAR_LIMIT else text[: CELL_CHAR_LIMIT - 1] + "…"


def json_safe_cell(value):
    """Coerce one parsed cell to a JSON-serialisable primitive.

    openpyxl returns real `datetime`/`date`/`time` objects for date-formatted
    cells and `Decimal` shows up via CSV/typed paths; `json.dumps` — and so
    `WebSocket.send_json` — raises `TypeError` on all of them, which would kill
    the whole broadcast (and therefore the ingest run) over one date column.
    Non-finite floats are stringified too: `json.dumps` emits bare `NaN`/
    `Infinity`, which is invalid JSON and breaks `JSON.parse` in the browser.
    Anything unrecognised is stringified rather than dropped.
    """
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, (datetime, date, time)):
        return _truncate(value.isoformat())
    if isinstance(value, Decimal):
        return _truncate(str(value))
    return _truncate(str(value))


def sheet_preview(sheet: ParsedSheet) -> dict:
    """The capped, JSON-safe shape of a parsed sheet, for the ROWS_FOUND event.

    `headers` is the *named* subset of the detected header row — exactly the keys
    the row dicts carry. Blank header cells are dropped here for the same reason
    `_sheet_from_values` drops them from the rows, and because openpyxl happily
    reports thousands of trailing empty columns for a sheet that merely has stray
    formatting.
    """
    headers = [_truncate(header) for header in sheet.headers if header]
    return {
        "headers": headers,
        "sample_rows": [
            # keys truncated the same way as `headers` above, so a pathologically
            # long header still matches between the two lists
            {_truncate(str(key)): json_safe_cell(value) for key, value in row.items()}
            for row in sheet.rows[:SAMPLE_ROW_LIMIT]
        ],
        "total_rows": len(sheet.rows),
    }


def _parse_csv(path: str, filename: str) -> list[ParsedSheet]:
    import csv
    from pathlib import Path

    # Sniff the delimiter rather than assuming a comma: Indian ERP exports are
    # frequently semicolon- or tab-separated, and a wrong guess yields one
    # giant column that classifies as "unknown" with no obvious cause.
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        values = [list(row) for row in csv.reader(handle, dialect)]
    if not values:
        raise RuntimeError(f"{filename} is empty")
    return [_sheet_from_values(Path(filename).stem, "CSV", values)]


def parse_workbook(path: str, filename: str) -> list[ParsedSheet]:
    """Parse an uploaded table into classified sheets.

    Accepts what the upload UI accepts. `.xls` is deliberately rejected with a
    named reason instead of being handed to openpyxl, which only reads the OOXML
    formats and fails on the legacy BIFF one with an opaque zipfile error.
    """
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if suffix == "csv":
        return _parse_csv(path, filename)
    if suffix == "xls":
        raise RuntimeError("Legacy .xls isn't supported — re-save it as .xlsx or .csv and upload again")

    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for Excel ingest") from exc
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    return [
        _sheet_from_values(sheet.title, "OPENPYXL", [list(row) for row in sheet.iter_rows(values_only=True)])
        for sheet in workbook.worksheets
    ]

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


# --- ENTITIES_FOUND payload -----------------------------------------------------

_VENDOR_NAME_HINTS = ("vendor name", "supplier name", "party name", "vendor", "supplier", "party")
_GSTIN_HINTS = ("gstin", "gst no", "gst number", "gst")
_SKU_HINTS = ("sku", "item code", "part no", "part number", "material", "item", "product")
# Same reasoning as SAMPLE_ROW_LIMIT: this rides the same ring buffer, so the
# inspectable merge evidence is capped rather than sent whole.
MERGED_GROUP_PREVIEW_LIMIT = 5
MERGED_GROUP_NAME_LIMIT = 4
# resolve_vendor_names compares each name against every group anchor with
# SequenceMatcher, so it's ~O(rows x distinct vendors). That's nothing on a
# 200-row vendor master and minutes on a 50k-line purchase log, which would peg
# a worker thread for the whole ingest. Past this many rows we count exact
# normalized names instead — cheaper, still better than the row count, and
# entity_basis reports which of the two actually ran.
FUZZY_RESOLVE_ROW_LIMIT = 2000


def _pick_column(headers: list[str], hints: tuple[str, ...]) -> str | None:
    """Exact header match first, then substring — so "vendor name" beats "vendor id"."""
    for hint in hints:
        for header in headers:
            if header == hint: return header
    for hint in hints:
        for header in headers:
            if hint in header: return header
    return None


def count_entities(sheet: ParsedSheet) -> dict:
    """How many *distinct real-world things* this sheet describes, and by what rule.

    `row_count` counts lines in a spreadsheet; this counts the entities those
    lines resolve to, which is a genuinely different number — 40 purchase-log
    lines are typically ~9 vendors, and a vendor master with "Bharat Steels" and
    "Bharat Steel Pvt. Ltd." on separate rows is one vendor, not two. Vendor
    sheets go through `resolve_vendor_names` (fuzzy + GSTIN merge); SKU-keyed
    sheets are counted by distinct SKU. When no identity column can be found the
    count degrades to the row count, and `entity_basis` says exactly that so the
    UI never presents the same number twice as if it were two facts.
    """
    headers = [header for header in sheet.headers if header]

    name_column = _pick_column(headers, _VENDOR_NAME_HINTS)
    if name_column and sheet.classification in ("vendor_master", "purchase_log"):
        gstin_column = _pick_column(headers, _GSTIN_HINTS)
        records = [
            {
                "vendor_name": str(row.get(name_column) or "").strip(),
                "gstin": str(row.get(gstin_column) or "").strip() if gstin_column else "",
            }
            for row in sheet.rows
        ]
        named = sum(1 for record in records if record["vendor_name"])
        if len(records) > FUZZY_RESOLVE_ROW_LIMIT:
            distinct_names = {
                normalize_vendor_name(record["vendor_name"])
                for record in records
                if record["vendor_name"]
            }
            return {
                "entity_count": len(distinct_names),
                "entity_kind": "vendor",
                "entity_basis": "DISTINCT_VENDOR_NAMES",
                "entity_source_column": name_column,
                "named_row_count": named,
                "merged_group_count": 0,
                "merged_groups": [],
            }
        resolved = resolve_vendor_names(records)
        return {
            "entity_count": resolved["unique_count"],
            "entity_kind": "vendor",
            "entity_basis": "RESOLVED_VENDOR_NAMES",
            "entity_source_column": name_column,
            "named_row_count": named,
            "merged_group_count": len(resolved["merged_groups"]),
            "merged_groups": [
                [_truncate(name) for name in group[:MERGED_GROUP_NAME_LIMIT]]
                for group in resolved["merged_groups"][:MERGED_GROUP_PREVIEW_LIMIT]
            ],
        }

    sku_column = _pick_column(headers, _SKU_HINTS)
    if sku_column and sheet.classification in ("inventory", "rate_card", "purchase_log"):
        distinct = {
            str(row.get(sku_column)).strip().upper()
            for row in sheet.rows
            if str(row.get(sku_column) or "").strip()
        }
        return {
            "entity_count": len(distinct),
            "entity_kind": "sku",
            "entity_basis": "DISTINCT_SKU",
            "entity_source_column": sku_column,
            "named_row_count": sum(1 for row in sheet.rows if str(row.get(sku_column) or "").strip()),
            "merged_group_count": 0,
            "merged_groups": [],
        }

    return {
        "entity_count": len(sheet.rows),
        "entity_kind": "row",
        "entity_basis": "ROWS_UNRESOLVED",
        "entity_source_column": None,
        "named_row_count": len(sheet.rows),
        "merged_group_count": 0,
        "merged_groups": [],
    }
