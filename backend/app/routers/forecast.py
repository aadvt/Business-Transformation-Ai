from fastapi import APIRouter, Depends, HTTPException

from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.forecast import Forecast

router = APIRouter(prefix="/api/v1/forecast", tags=["forecast"], dependencies=[Depends(require_api_key)])


@router.get("/{sku}", response_model=Forecast)
def get_forecast(sku: str) -> Forecast:
    f = store.forecasts.get(sku)
    if f is None:
        raise HTTPException(status_code=404, detail="No forecast available for this SKU")
    return f
