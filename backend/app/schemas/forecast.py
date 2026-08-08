from app.schemas.common import ApiModel
from app.schemas.enums import ForecastModel


class ForecastPoint(ApiModel):
    at: str
    value: float


class Forecast(ApiModel):
    sku: str
    history: list[ForecastPoint]
    forecast: list[ForecastPoint]
    reorder_point: float
    projected_breach_at: str | None
    model: ForecastModel
