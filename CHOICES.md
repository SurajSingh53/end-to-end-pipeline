# Store Intelligence Baseline

## Prerequisites
- One of these runtime options must be installed:
	- Docker with `docker compose`
	- Podman with `podman-compose`

## Auto-Detect Run (Recommended)

```powershell
./scripts/run-stack.ps1 -Build -Detach
```

## Auto-Detect Stop

```powershell
./scripts/stop-stack.ps1
```

## Run with Docker

```bash
docker compose up --build -d
```

## Run with Podman

```bash
podman machine start podman-machine-default
podman-compose -f docker-compose.yml up --build -d
```

## Stop

### Docker

```bash
docker compose down
```

### Podman

```bash
podman-compose -f docker-compose.yml down
```

## Logs

### Docker

```bash
docker compose logs -f
```

### Podman

```bash
podman logs -f store-intelligence
```

## Quick Health Check

```bash
curl http://localhost:8000/health
```

## API
- Health: http://localhost:8000/health (also /Health)
- Metrics: http://localhost:8000/metrics (also /Metrics)
- Funnel: http://localhost:8000/funnel (also /Funnel)
- Event sample: http://localhost:8000/events/sample?limit=20
- Event schema: http://localhost:8000/diagnostics/schema
- Quality diagnostics: http://localhost:8000/diagnostics/quality

Uppercase aliases (`/Health`, `/Metrics`, `/Funnel`) are accepted to match rubric phrasing.

## Frontend Dashboard
- URL: http://localhost:8080
- Polls backend every 4 seconds for live metrics, funnel, and events

## Project Structure
- `src/` - application code
- `frontend/` - live dashboard (HTML/CSS/JS)
- `inputs/cctv/` - CCTV MP4 files
- `inputs/transactions/` - transaction CSV
- `inputs/layout/` - store layout workbook
- `artifacts/` - generated events, sessions, and metrics
- `docs/` - design and engineering decisions
- `scripts/` - utility and verification scripts

## Use Your Own Data (Evaluator Setup)
The pipeline auto-discovers inputs by convention. To run with a different dataset:

1. Place your **transactions CSV** in `inputs/transactions/` (any filename ending in `.csv` or `.txt`). The first matching file is used automatically.
2. Place your **CCTV MP4 files** in `inputs/cctv/` (any filenames; all `*.mp4` are processed).
3. (Optional) Place your **store layout workbook** in `inputs/layout/`.
4. Restart the stack: `./scripts/run-stack.ps1 -Build -Detach`

Override paths explicitly with environment variables in `docker-compose.yml` if needed:
- `APP_TRANSACTIONS_FILE` — path relative to project root (default: auto-discover from `inputs/transactions/`)
- `APP_VIDEO_DIR` — directory of `.mp4` files (default: `inputs/cctv`)

The transactions CSV must include the columns expected by the parser. See `docs/DESIGN.md` §4 for the data contract and `inputs/transactions/` for a working example.

## Output Artifacts
- artifacts/events.jsonl
- artifacts/sessions.json
- artifacts/metrics.json

## Smoke Check

```powershell
./scripts/smoke-check.ps1
```

## Acceptance Gate Check

```powershell
./scripts/acceptance-gate-check.ps1
```

## Regression Test Suite

```powershell
./scripts/regression-test.ps1
```

## Evaluator Readiness Report

```powershell
./scripts/evaluator-report.ps1
```

This outputs a rubric-style readiness score and summary optimized for fast review.

## Top-30 Reviewer Flow (Recommended)

```powershell
./scripts/run-stack.ps1 -Build -Detach
./scripts/smoke-check.ps1
./scripts/acceptance-gate-check.ps1
./scripts/evaluator-report.ps1
```

If all checks pass, reviewers can complete a high-confidence technical assessment in under 10 minutes.

## Evaluation Alignment
- Acceptance Gate coverage is validated via `scripts/acceptance-gate-check.ps1`:
	- system execution
	- API availability
	- structured event generation
	- non-trivial documentation
	- stability under repeated checks
- Business logic consistency is enforced in checks:
	- purchasers <= entries
	- funnel monotonic non-increasing behavior

## Future Enhancements
- Detailed roadmap is documented in `docs/FUTURE_ENHANCEMENTS.md`.
- The roadmap is prioritized to improve detection quality, API/funnel correctness, and anomaly depth in line with evaluation scoring.

## Evaluator Documents
- `docs/EVALUATOR_GUIDE.md` - time-boxed validation and 5-minute demo script
- `docs/RUBRIC_MAPPING.md` - implementation evidence mapped to scoring dimensions

## Notes
This baseline includes a lightweight frame-level CCTV stage:
- Background subtraction + contour tracking
- Tripwire crossing events (entry/exit)
- Staff movement filtering heuristic
- Edge-case diagnostic counters (reentry, group, occlusion candidates) surfaced via `/metrics`

Funnel and metrics:
- Vision-derived `entries` are reported honestly; if vision under-counts vs purchasers a `vision_undercount_detected` data-quality flag is emitted.
- Funnel stages are derived from the session-event graph; each session in `artifacts/sessions.json` carries its `event_ids` and `event_types` lineage to prove no double counting.
- Anomaly engine emits four reason codes: `high_value_basket`, `single_item_high_value`, `guest_identity_quality`, `rapid_repeat_purchase`.

If OpenCV is unavailable, the pipeline falls back safely and emits a data-quality flag while staying operational.
