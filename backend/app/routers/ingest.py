import asyncio
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, UploadFile
from pydantic import BaseModel

from app.constants import DEFAULT_ORG_ID
from app.schemas.enums import WSEventType
from app.services.ingest.parser import count_entities, parse_workbook, sheet_preview
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

async def _process(ingest_id: str, files: list[tuple[str, str, str]]) -> None:
    for file_id, name, path in files:
        async def progress(stage, **extra):
            await live_feed.broadcast(WSEventType.INGEST_PROGRESS, {"ingest_id": ingest_id, "file_id": file_id, "name": name, "stage": stage, **extra})
        try:
            await progress("PARSING_STARTED")
            sheets = await asyncio.to_thread(parse_workbook, path, name)
            await progress("SHEETS_FOUND", sheet_count=len(sheets))
            for sheet in sheets:
                # headers/sample_rows/total_rows let the UI render the actual data
                # landing instead of a counter. Both helpers are capped and
                # JSON-coerced — see SAMPLE_ROW_LIMIT/CELL_CHAR_LIMIT in parser.py.
                preview = sheet_preview(sheet)
                await progress(
                    "ROWS_FOUND",
                    sheet=sheet.name,
                    classification=sheet.classification,
                    confidence=sheet.confidence,
                    row_count=len(sheet.rows),
                    headers=preview["headers"],
                    sample_rows=preview["sample_rows"],
                    total_rows=preview["total_rows"],
                )
                # entity_count is deliberately NOT len(sheet.rows): it's the count
                # of distinct resolved entities (fuzzy-merged vendors, or distinct
                # SKUs), and entity_kind/entity_basis name what was actually
                # counted so the stage reports a fact rather than a repeat.
                # to_thread because resolve_vendor_names is O(rows x groups)
                # SequenceMatcher work — seconds of blocking on a big sheet, and
                # blocking the loop here stalls every other request (CLAUDE.md).
                entities = await asyncio.to_thread(count_entities, sheet)
                await progress("ENTITIES_FOUND", sheet=sheet.name, **entities)
            # sheets[0].parser is the parser that actually ran (OPENPYXL or CSV);
            # this used to be hardcoded "OPENPYXL" and lied for CSV uploads.
            await progress("DEDUPE_COMPLETE", parser=sheets[0].parser if sheets else "NONE", status="COMPLETED")
        except Exception as exc:
            await progress("FAILED", error=str(exc)[:300])
        finally:
            try: os.unlink(path)
            except OSError: pass

@router.post("/files")
async def ingest_files(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)):
    ingest_id = str(uuid.uuid4()); queued = []; temp_files = []
    for upload in files:
        file_id = str(uuid.uuid4()); suffix = Path(upload.filename or "upload.xlsx").suffix or ".xlsx"
        fd, path = tempfile.mkstemp(suffix=suffix); os.close(fd)
        with open(path, "wb") as target: target.write(await upload.read())
        temp_files.append((file_id, upload.filename or "upload.xlsx", path)); queued.append({"file_id": file_id, "name": upload.filename or "upload.xlsx", "status": "QUEUED"})
    background_tasks.add_task(_process, ingest_id, temp_files)
    return {"ingest_id": ingest_id, "files": queued}
