from contextlib import asynccontextmanager
import logging
from time import perf_counter

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from .config import AppConfig, load_config
from .models import FunnelResponse, MetricsResponse
from .pipeline import Snapshot, build_snapshot, persist_snapshot


class AppState:
    config: AppConfig
    snapshot: Snapshot


state = AppState()
logger = logging.getLogger("store_intelligence.api")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _ensure_state() -> None:
    if not hasattr(state, "config"):
        state.config = load_config()
    if not hasattr(state, "snapshot"):
        state.snapshot = build_snapshot(state.config)
        persist_snapshot(state.config, state.snapshot)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.config = load_config()
    state.snapshot = build_snapshot(state.config)
    persist_snapshot(state.config, state.snapshot)
    yield


app = FastAPI(
    title="Store Intelligence API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
    latency_ms = round((perf_counter() - started) * 1000, 2)
    logger.info(
        "request method=%s path=%s status=%s latency_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        latency_ms,
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    _ensure_state()
    return {"status": "ok", "service": "store-intelligence"}


@app.get("/Health")
def health_alias() -> dict[str, str]:
    return health()


@app.get("/metrics", response_model=MetricsResponse)
def metrics() -> dict:
    _ensure_state()
    return state.snapshot.metrics


@app.get("/Metrics", response_model=MetricsResponse)
def metrics_alias() -> dict:
    return metrics()


@app.get("/funnel", response_model=FunnelResponse)
def funnel() -> dict:
    _ensure_state()
    return state.snapshot.funnel


@app.get("/Funnel", response_model=FunnelResponse)
def funnel_alias() -> dict:
    return funnel()


@app.get("/events/sample")
def events_sample(limit: int = 50) -> dict:
    _ensure_state()
    safe_limit = max(1, min(limit, 200))
    return {
        "generated_at": state.snapshot.generated_at,
        "count": safe_limit,
        "events": state.snapshot.events[:safe_limit],
    }


@app.get("/diagnostics/schema")
def diagnostics_schema() -> dict:
    _ensure_state()
    return {
        "event_schema": {
            "required_fields": [
                "event_id",
                "event_type",
                "event_time",
                "store_id",
                "session_id",
                "confidence",
                "dedupe_key",
                "reason_code",
                "source",
            ],
            "optional_fields": [
                "camera_id",
                "zone_id",
                "order_id",
                "customer_number",
            ],
        },
        "supported_event_types": [
            "entry_confirmed",
            "transaction_linked",
            "exit_confirmed",
            "anomaly_flagged",
            "staff_movement",
        ],
    }


@app.get("/diagnostics/quality")
def diagnostics_quality() -> dict:
    _ensure_state()
    metrics_snapshot = state.snapshot.metrics
    funnel_snapshot = state.snapshot.funnel
    entries = int(metrics_snapshot.get("entries", 0))
    purchasers = int(metrics_snapshot.get("purchasers", 0))
    invariants = {
        "purchasers_within_entries": purchasers <= entries,
        "funnel_monotonic_non_increasing": bool(funnel_snapshot.get("is_monotonic_non_increasing", False)),
    }
    return {
        "generated_at": state.snapshot.generated_at,
        "invariants": invariants,
        "anomaly_reason_counts": metrics_snapshot.get("anomaly_reason_counts", {}),
        "vision_edge_case_signals": metrics_snapshot.get("vision_edge_case_signals", {}),
        "data_quality_flags": metrics_snapshot.get("data_quality_flags", []),
    }
