from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for all response/request models — camelCase-free, strict extra."""

    model_config = ConfigDict(extra="forbid")


class Money(ApiModel):
    paise: int
    display: str


class Envelope(ApiModel):
    """Fields every domain object response must include."""

    id: str
    created_at: str
    updated_at: str
