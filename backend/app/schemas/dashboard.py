from app.schemas.common import ApiModel
from app.schemas.enums import DisruptionStage


class StageCount(ApiModel):
    stage: DisruptionStage
    count: int


class DashboardSummary(ApiModel):
    active_disruptions: int
    exposure_at_risk_paise: int
    exposure_at_risk_display: str
    exposure_mitigated_paise: int
    exposure_mitigated_display: str
    disruptions_closed_today: int
    stage_counts: list[StageCount]
    vendors_dues_total_paise: int
    vendors_dues_total_display: str
    updated_at: str
