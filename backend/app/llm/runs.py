"""Records every LLM and Guardian call as an `agent_runs` row.

Deliberately fail-soft: observability must never be the reason a demo call
fails. If the DB is unreachable (or we're running with USE_MOCKS / no DB at
all), recording degrades to a log line instead of raising.
"""

import logging
import uuid
from datetime import datetime
from typing import Protocol

from app.db.models import AgentRun
from app.schemas.money import utc_now

logger = logging.getLogger("sanjeevani.llm.runs")

SUMMARY_MAX_CHARS = 500
_AGENT_COLUMN_MAX_CHARS = 30


def truncate(text: str | None, limit: int = SUMMARY_MAX_CHARS) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AgentRunRecorder(Protocol):
    def record(
        self,
        *,
        agent: str,
        status: str,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
        model_id: str | None,
        input_summary: str,
        output_summary: str,
        error: str | None = None,
        token_usage: dict | None = None,
        disruption_id: str | None = None,
    ) -> None: ...


class NullAgentRunRecorder:
    """Used by tests and by scripts that shouldn't write to the database."""

    def record(self, **kwargs) -> None:
        return None


class DbAgentRunRecorder:
    """Writes to `agent_runs` in its own short-lived session.

    A separate session (rather than joining the caller's request transaction) is
    deliberate: an LLM call's observability record should survive even if the
    surrounding business transaction later rolls back — that's exactly the case
    you most want a trace of.
    """

    def record(
        self,
        *,
        agent: str,
        status: str,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
        model_id: str | None,
        input_summary: str,
        output_summary: str,
        error: str | None = None,
        token_usage: dict | None = None,
        disruption_id: str | None = None,
    ) -> None:
        try:
            from app.db.session import SessionLocal

            with SessionLocal() as session:
                session.add(
                    AgentRun(
                        id=str(uuid.uuid4()),
                        disruption_id=disruption_id,
                        agent=agent[:_AGENT_COLUMN_MAX_CHARS],
                        status=status,
                        started_at=started_at,
                        ended_at=ended_at,
                        latency_ms=latency_ms,
                        model_id=model_id,
                        input_summary=truncate(input_summary),
                        output_summary=truncate(output_summary),
                        error=truncate(error, 1000) or None,
                        token_usage=token_usage,
                    )
                )
                session.commit()
        except Exception:
            logger.warning("agent_run_record_failed", extra={"agent": agent}, exc_info=True)


def default_recorder() -> AgentRunRecorder:
    from app.config import settings

    # use_mocks means "no DB at all"; llm_provider=stub means "no network at
    # all" (this is what the test suite sets) — either one rules out opening a
    # real Postgres connection just to log a call that didn't really happen.
    if settings.use_mocks or settings.llm_provider == "stub":
        return NullAgentRunRecorder()
    return DbAgentRunRecorder()


__all__ = [
    "AgentRunRecorder",
    "DbAgentRunRecorder",
    "NullAgentRunRecorder",
    "default_recorder",
    "truncate",
    "utc_now",
]
