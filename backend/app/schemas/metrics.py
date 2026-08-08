from app.schemas.common import ApiModel
from app.schemas.enums import IntegrationStatus


class LatencyStat(ApiModel):
    p50: float
    p95: float
    last: float


class Latency(ApiModel):
    detection_to_alert_seconds: LatencyStat
    alert_to_decision_seconds: LatencyStat
    decision_to_negotiated_seconds: LatencyStat
    end_to_end_seconds: LatencyStat


class Totals(ApiModel):
    exposure_identified_paise: int
    exposure_identified_display: str
    exposure_mitigated_paise: int
    exposure_mitigated_display: str
    disruptions_closed: int


class Integrations(ApiModel):
    watsonx: IntegrationStatus
    guardian: IntegrationStatus
    supermemory: IntegrationStatus
    verification: IntegrationStatus
    ttm: IntegrationStatus
    orchestrate: IntegrationStatus
    neon: IntegrationStatus


class MetricsDemo(ApiModel):
    latency: Latency
    totals: Totals
    integrations: Integrations
