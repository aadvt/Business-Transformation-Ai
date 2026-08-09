from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import forecast as repo
from app.schemas.forecast import Forecast

router = APIRouter(prefix="/api/v1/forecast", tags=["forecast"], dependencies=[Depends(require_api_key)])


@router.get("/{sku}", response_model=Forecast)
def get_forecast(sku: str, session: Session = Depends(get_session)) -> Forecast:
    if settings.use_mocks:
        f = store.forecasts.get(sku)
    else:
        f = repo.get_forecast(session, sku)
    if f is None:
        raise HTTPException(status_code=404, detail="No forecast available for this SKU")
    return f
