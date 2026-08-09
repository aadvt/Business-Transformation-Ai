"""Agent base class.

Every agent (Sentinel, Diagnosis, Sourcing, ...) subclasses `Agent` and
implements `_execute(ctx) -> AgentResult`. `Agent.run()` wraps that call with
the behaviour every agent must have, so no agent can forget it:

  - timed, so latency is always known
  - always writes one `agent_runs` row (agent=self.name, separate from any
    finer-grained rows the agent's own LLM/Guardian calls write via
    app.llm.runs — this row is the whole-agent-invocation trace)
  - always writes one append-only `audit_log` entry via
    app.services.audit.append_audit — never bypass that helper
  - NEVER lets an exception escape. A crashing agent becomes
    AgentResult(status=ERROR, error=...) and the caller (the orchestrator, or
    a router) decides what to do next. An agent must never be the reason an
    API request 500s.
  - on an exception, rolls back the session first — a half-finished write from
    a failed attempt must not leak into the audit/agent_runs commit that
    follows, and must not poison the caller's next statement on this session.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.llm.runs import AgentRunRecorder, default_recorder, truncate
from app.schemas.enums import AgentName, AgentStatus
from app.schemas.money import utc_now
from app.services.audit import append_audit

logger = logging.getLogger("sanjeevani.agents")


@dataclass
class AgentContext:
    session: Session
    org_id: str
    disruption_id: str | None = None
    # Agent-specific input. Each agent documents what it expects here rather
    # than the base class enumerating every agent's needs.
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    status: AgentStatus
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == AgentStatus.DONE


class Agent(ABC):
    name: AgentName

    def __init__(self, recorder: AgentRunRecorder | None = None) -> None:
        self._recorder = recorder if recorder is not None else default_recorder()

    @abstractmethod
    def _execute(self, ctx: AgentContext) -> AgentResult:
        """Do the agent's work. May raise — `run()` contains it."""
        raise NotImplementedError

    def run(self, ctx: AgentContext) -> AgentResult:
        started_at = utc_now()
        start = time.monotonic()

        try:
            result = self._execute(ctx)
        except Exception as exc:  # noqa: BLE001 - deliberate: an agent must never propagate
            logger.error(
                "agent_crashed",
                extra={"agent": self.name.value, "disruption_id": ctx.disruption_id},
                exc_info=True,
            )
            ctx.session.rollback()  # discard whatever partial writes the failed attempt made
            result = AgentResult(status=AgentStatus.ERROR, error=f"{type(exc).__name__}: {exc}")

        latency_ms = (time.monotonic() - start) * 1000
        ended_at = utc_now()

        append_audit(
            ctx.session,
            org_id=ctx.org_id,
            disruption_id=ctx.disruption_id,
            actor_type="AGENT",
            actor=self.name.value,
            action=f"{self.name.value}_RUN",
            detail={"status": result.status.value, "summary": result.summary, "error": result.error},
            at=ended_at,
        )
        ctx.session.commit()

        self._recorder.record(
            agent=self.name.value,
            status=result.status.value,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            model_id=None,
            input_summary=truncate(str(ctx.input)),
            output_summary=truncate(result.summary or str(result.data)),
            error=result.error,
            token_usage=None,
            disruption_id=ctx.disruption_id,
        )

        logger.info(
            "agent_run",
            extra={
                "agent": self.name.value,
                "status": result.status.value,
                "latency_ms": round(latency_ms, 1),
                "disruption_id": ctx.disruption_id,
            },
        )
        return result
