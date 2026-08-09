from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.enums import GraphNodeKind, GraphNodeState


class ImpactNode(ApiModel):
    id: str
    kind: GraphNodeKind
    layer: int
    label: str
    state: GraphNodeState
    badges: list[str] = Field(default_factory=list)


class ImpactEdge(ApiModel):
    id: str
    source: str
    target: str
    state: GraphNodeState


class ImpactSummary(ApiModel):
    """Reuses the disruption's own latest exposure_calcs row — never a second,
    independently-computed number. See app/services/impact.py's docstring."""

    exposure_total_paise: int
    exposure_total_display: str
    exposure_confidence: float
    exposure_calc_id: str | None
    severity_tier: int
    tier_thresholds_paise: dict[str, int]


class ImpactGraph(ApiModel):
    disruption_id: str
    nodes: list[ImpactNode]
    edges: list[ImpactEdge]
    summary: ImpactSummary
    computed_at: str
