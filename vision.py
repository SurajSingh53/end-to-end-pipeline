from pydantic import BaseModel, Field


class Event(BaseModel):
    event_id: str
    event_type: str
    event_time: str
    store_id: str
    camera_id: str | None = None
    zone_id: str | None = None
    session_id: str
    order_id: str | None = None
    customer_number: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    dedupe_key: str
    reason_code: str
    source: str


class StageCount(BaseModel):
    stage: str
    count: int


class FunnelResponse(BaseModel):
    generated_at: str
    stages: list[StageCount]
    is_monotonic_non_increasing: bool


class MetricsResponse(BaseModel):
    generated_at: str
    store_id: str
    entries: int
    purchasers: int
    transactions: int
    conversion_rate: float
    anomaly_count: int
    data_quality_flags: list[str]
    vision_processing_mode: str
    cameras_processed: int
    vision_entry_events: int
    vision_exit_events: int
    staff_tracks_detected: int
    anomaly_reason_counts: dict[str, int]
    vision_edge_case_signals: dict[str, int]
