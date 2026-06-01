import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    transactions_file: Path
    video_dir: Path
    event_store: Path
    session_store: Path
    metrics_store: Path



def _discover_transactions_file(root_dir: Path) -> Path:
    inputs_dir = root_dir / "inputs" / "transactions"
    if inputs_dir.is_dir():
        for pattern in ("*.csv", "*.txt"):
            matches = sorted(inputs_dir.glob(pattern))
            if matches:
                return matches[0]
    return root_dir / "inputs" / "transactions" / "transactions.csv"


def load_config() -> AppConfig:
    root_dir = Path(__file__).resolve().parents[1]
    configured = os.getenv("APP_TRANSACTIONS_FILE")
    if configured:
        transactions_file = root_dir / configured
    else:
        transactions_file = _discover_transactions_file(root_dir)
    video_dir = root_dir / os.getenv("APP_VIDEO_DIR", "inputs/cctv")
    event_store = root_dir / os.getenv("APP_EVENT_STORE", "data/events.jsonl")
    session_store = root_dir / os.getenv("APP_SESSION_STORE", "data/sessions.json")
    metrics_store = root_dir / os.getenv("APP_METRICS_STORE", "data/metrics.json")

    return AppConfig(
        root_dir=root_dir,
        transactions_file=transactions_file,
        video_dir=video_dir,
        event_store=event_store,
        session_store=session_store,
        metrics_store=metrics_store,
    )

    def _resolve_path(root_dir: Path, env_key: str, default_path: str, legacy_path: str | None = None) -> Path:
        configured = os.getenv(env_key)
        if configured:
            return root_dir / configured

        preferred = root_dir / default_path
        if preferred.exists():
            return preferred

        if legacy_path:
            legacy = root_dir / legacy_path
            if legacy.exists():
                return legacy

        return preferred

