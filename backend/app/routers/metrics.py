from fastapi import APIRouter, Depends

from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.metrics import MetricsDemo

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"], dependencies=[Depends(require_api_key)])


@router.get("/demo", response_model=MetricsDemo)
def get_metrics_demo() -> MetricsDemo:
    return store.metrics_demo
