# Store Intelligence System Design

## 1. Objective
Build an end-to-end pipeline from CCTV streams and transaction data that produces business metrics such as conversion and funnel progression with deterministic API outputs.

## 2. Scope of This Implementation
This implementation is an execution-first baseline that satisfies the mandatory acceptance criteria:
- Runs using docker compose
- Exposes API endpoints including /metrics
- Generates structured events
- Persists outputs for reviewer inspection
- Stays stable during basic execution

It now includes a bounded frame-level vision pass across CCTV clips using motion segmentation + tripwire crossing.

## 3. Architecture

### 3.1 Components
- Ingestion
  - Transaction parser from inputs/transactions/brigade-bangalore-2026-04-10.csv
  - CCTV asset discovery from inputs/cctv/*.mp4
- Event Pipeline
  - Vision motion tracker over CCTV footage
  - Tripwire crossing classification for entry/exit
  - Staff movement filtering heuristic
  - Session creation per order
  - Structured events: entry_confirmed, transaction_linked, exit_confirmed, anomaly_flagged
- Metric Engine
  - Computes entries, purchasers, transactions, conversion rate, anomaly count
  - Produces funnel stages from the session-event graph with monotonic check
  - Surfaces anomaly reason counts and vision edge-case signals
- API Layer (FastAPI)
  - /health (alias /Health)
  - /metrics (alias /Metrics)
  - /funnel (alias /Funnel)
  - /events/sample
  - /diagnostics/schema
  - /diagnostics/quality
- Persistence
  - artifacts/events.jsonl
  - artifacts/sessions.json (sessions carry event_ids + event_types lineage)
  - artifacts/metrics.json

### 3.2 Runtime Sequence
1. App starts
2. Pipeline reads transactions and available camera files
3. Pipeline emits deterministic structured events and session records
4. Metrics and funnel are computed and persisted
5. Endpoints serve in-memory snapshot

## 4. Data Contracts

### 4.1 Event Schema
Required fields:
- event_id
- event_type
- event_time
- store_id
- session_id
- confidence
- dedupe_key
- reason_code
- source

Optional fields:
- camera_id
- zone_id
- order_id
- customer_number

### 4.2 Session Schema
- session_id
- order_id
- customer_number
- store_id
- entry_time
- transaction_time
- exit_time
- camera_id
- item_count
- total_amount
- is_guest

## 5. Business Logic
- Entry and exit events are generated from camera footage via tripwire crossings.
- Transactions are linked at line-item level for structured auditability.
- Conversion rate = purchasers / entries, computed from honest vision-derived entries (no inflation). When vision under-counts, a `vision_undercount_detected` data-quality flag is emitted.
- Funnel stages are derived from the session-event graph (engaged_visitors and billing_zone_visitors require sessions to actually carry transaction-linked events) and validated for monotonic non-increasing behavior.
- Rule-based anomaly engine emits four reasons: `high_value_basket`, `single_item_high_value`, `guest_identity_quality`, `rapid_repeat_purchase`.

## 6. Edge Cases Addressed in Baseline
- Placeholder customer numbers (1000000000) are flagged as data quality issues.
- Camera inventory can be empty; fallback camera ID is emitted.
- Numeric parsing resilience for malformed values.
- Staff-like long-stationary movement near counter zones is filtered from entry/exit counts.
- Diagnostic counters for re-entry candidates, group crossings, and occlusion candidates are exposed in `/metrics.vision_edge_case_signals`.
- Vision under-count vs purchasers surfaced via `vision_undercount_detected` flag rather than silently inflating `entries`.

## 7. Known Limitations
- Current detector is classical motion-based tracking (not person detector + re-identification), so occlusion and dense crowd scenes can still degrade count quality.
- Re-entry, staff filtering, and occlusion handling are represented as extensible hooks, not full CV implementation yet.
- Store layout spreadsheet is not yet mapped into zone geometry.

## 8. Next Engineering Milestones
1. Replace synthetic entry/exit with frame-based detection and tracking.
2. Add re-identification and session continuity for re-entry handling.
3. Integrate layout zone mapping for camera-to-zone attribution.
4. Add richer anomaly set and confidence calibration.

## 9. Evaluation Criteria Alignment

### 9.1 Acceptance Gate
- System Execution: containerized startup via compose for one-command run.
- API Availability: `/metrics`, `/funnel`, `/health`, `/events/sample` available.
- Event Generation: structured events with required fields and reason codes.
- Documentation: DESIGN and CHOICES maintained as non-trivial artifacts.
- Stability: startup retries and repeated endpoint checks via scripts.

### 9.2 Detection Pipeline Scoring
- Entry/Exit Accuracy: tripwire crossing with deterministic event IDs and dedupe keys.
- Edge Case Handling: initial staff filtering and bounded runtime controls.
- Event Quality: schema completeness and confidence tagging.

### 9.3 API and Business Logic Scoring
- Endpoint Correctness: typed response models and consistent payload structure.
- Funnel Logic: monotonic validation and anti-double-count guardrails.
- Anomaly Detection: baseline rules implemented with extensible rule framework.

## 10. Phased Enhancement Plan (Evaluation-First)
1. Detection v2: add person detector + tracker + re-identification to improve re-entry/group handling.
2. Zone Intelligence: ingest store layout to bind movement and sales to zones.
3. Funnel Robustness: session stitching across cameras and explicit no-double-count reconciliation.
4. Anomaly v2: add dwell-time anomalies, traffic spikes, and conversion-drop alerts.
5. Reviewer UX: add one-command scoring summary output against rubric dimensions.
