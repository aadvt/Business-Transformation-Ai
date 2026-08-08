from typing import Any

from app.schemas.common import ApiModel
from app.schemas.enums import WSEventType


class WSEvent(ApiModel):
    event_id: str
    type: WSEventType
    at: str
    disruption_id: str | None = None
    payload: dict[str, Any]
