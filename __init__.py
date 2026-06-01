import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .vision import extract_vision_events


@dataclass
class Snapshot:
    generated_at: str
    events: list[dict[str, Any]]
    sessions: list[dict[str, Any]]
    metrics: dict[str, Any]
    funnel: dict[str, Any]



def _parse_timestamp(order_date: str, order_time: str) -> datetime:
    return datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")



def _safe_float(value: str, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback



def _read_transactions(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]



def _camera_for_order(order_id: str, camera_count: int) -> str:
    if camera_count <= 0:
        return "CAM_UNKNOWN"
    idx = int(order_id[-1]) % camera_count
    return f"CAM_{idx + 1}"


def _append_anomaly_event(
    events: list[dict[str, Any]],
    order_id: str,
    store_id: str,
    camera_id: str,
    session_id: str,
    event_time: str,
    customer_number: str,
    reason_code: str,
    confidence: float,
) -> None:
    events.append(
        {
            "event_id": f"EV_{order_id}_ANOM_{reason_code}",
            "event_type": "anomaly_flagged",
            "event_time": event_time,
            "store_id": store_id,
            "camera_id": camera_id,
            "zone_id": "billing_counter",
            "session_id": session_id,
            "order_id": order_id,
            "customer_number": customer_number,
            "confidence": confidence,
            "dedupe_key": f"anom:{order_id}:{reason_code}",
            "reason_code": reason_code,
            "source": "anomaly_rules_v2",
        }
    )



def build_snapshot(config: AppConfig) -> Snapshot:
    rows = _read_transactions(config.transactions_file)
    cameras = sorted([p for p in config.video_dir.glob("*.mp4")])
    camera_count = len(cameras)

    order_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        order_rows[row["order_id"]].append(row)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    default_store_id = rows[0]["store_id"] if rows else "UNKNOWN"

    vision_events, vision_summary, vision_flags = extract_vision_events(
        config.video_dir,
        default_store_id,
    )

    events: list[dict[str, Any]] = list(vision_events)
    sessions: list[dict[str, Any]] = []

    data_quality_flags: set[str] = set()
    data_quality_flags.update(vision_flags)

    for order_id, line_items in order_rows.items():
        first = line_items[0]
        ts = _parse_timestamp(first["order_date"], first["order_time"])
        session_id = f"SES_{order_id}"
        camera_id = _camera_for_order(order_id, camera_count)

        customer_number = first.get("customer_number") or "unknown"
        if customer_number == "1000000000":
            data_quality_flags.add("placeholder_customer_number_present")

        entry_time = (ts - timedelta(minutes=5)).replace(microsecond=0).isoformat() + "Z"
        txn_time = ts.replace(microsecond=0).isoformat() + "Z"
        exit_time = (ts + timedelta(minutes=10)).replace(microsecond=0).isoformat() + "Z"

        total_amount = 0.0
        item_count = 0
        for idx, item in enumerate(line_items, start=1):
            total_amount += _safe_float(item.get("total_amount", "0"))
            item_count += int(float(item.get("qty") or 0))
            events.append(
                {
                    "event_id": f"EV_{order_id}_TXN_{idx}",
                    "event_type": "transaction_linked",
                    "event_time": txn_time,
                    "store_id": item["store_id"],
                    "camera_id": camera_id,
                    "zone_id": "billing_counter",
                    "session_id": session_id,
                    "order_id": order_id,
                    "customer_number": customer_number,
                    "confidence": 0.95,
                    "dedupe_key": f"txn:{order_id}:{idx}:{item.get('sku', '')}",
                    "reason_code": "time_window_match",
                    "source": "sales_linker_v1",
                }
            )

        if total_amount > 5000:
            _append_anomaly_event(
                events=events,
                order_id=order_id,
                store_id=first["store_id"],
                camera_id=camera_id,
                session_id=session_id,
                event_time=txn_time,
                customer_number=customer_number,
                reason_code="high_value_basket",
                confidence=0.72,
            )

        if item_count <= 1 and total_amount >= 2000:
            _append_anomaly_event(
                events=events,
                order_id=order_id,
                store_id=first["store_id"],
                camera_id=camera_id,
                session_id=session_id,
                event_time=txn_time,
                customer_number=customer_number,
                reason_code="single_item_high_value",
                confidence=0.68,
            )

        if customer_number == "1000000000" and total_amount > 1000:
            _append_anomaly_event(
                events=events,
                order_id=order_id,
                store_id=first["store_id"],
                camera_id=camera_id,
                session_id=session_id,
                event_time=txn_time,
                customer_number=customer_number,
                reason_code="guest_identity_quality",
                confidence=0.6,
            )

        sessions.append(
            {
                "session_id": session_id,
                "order_id": order_id,
                "customer_number": customer_number,
                "store_id": first["store_id"],
                "entry_time": entry_time,
                "transaction_time": txn_time,
                "exit_time": exit_time,
                "camera_id": camera_id,
                "item_count": item_count,
                "total_amount": round(total_amount, 2),
                "is_guest": customer_number == "1000000000",
            }
        )

    sessions_by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        customer_number = str(session.get("customer_number") or "")
        if customer_number in {"", "unknown", "1000000000"}:
            continue
        sessions_by_customer[customer_number].append(session)

    for customer_sessions in sessions_by_customer.values():
        ordered = sorted(customer_sessions, key=lambda s: s["transaction_time"])
        for i in range(1, len(ordered)):
            prev_ts = datetime.fromisoformat(ordered[i - 1]["transaction_time"].replace("Z", "+00:00"))
            curr_ts = datetime.fromisoformat(ordered[i]["transaction_time"].replace("Z", "+00:00"))
            if (curr_ts - prev_ts) <= timedelta(minutes=20):
                _append_anomaly_event(
                    events=events,
                    order_id=ordered[i]["order_id"],
                    store_id=ordered[i]["store_id"],
                    camera_id=ordered[i]["camera_id"],
                    session_id=ordered[i]["session_id"],
                    event_time=ordered[i]["transaction_time"],
                    customer_number=ordered[i]["customer_number"],
                    reason_code="rapid_repeat_purchase",
                    confidence=0.67,
                )

    event_type_counts = defaultdict(int)
    for event in events:
        event_type_counts[event["event_type"]] += 1

    events_by_session: dict[str, set[str]] = defaultdict(set)
    event_ids_by_session: dict[str, list[str]] = defaultdict(list)
    for event in events:
        sid = event.get("session_id")
        if sid:
            events_by_session[sid].add(event["event_type"])
            eid = event.get("event_id")
            if eid:
                event_ids_by_session[sid].append(eid)

    for session in sessions:
        sid = session["session_id"]
        session["event_ids"] = list(event_ids_by_session.get(sid, []))
        session["event_types"] = sorted(events_by_session.get(sid, set()))

    vision_entries = int(vision_summary.get("entry_events", 0))
    purchaser_sessions = [
        s for s in sessions
        if "transaction_linked" in events_by_session.get(s["session_id"], set())
    ]
    purchasers = len(purchaser_sessions)
    transactions = event_type_counts["transaction_linked"]
    anomaly_count = event_type_counts["anomaly_flagged"]
    anomaly_reason_counts = dict(
        sorted(
            (
                (reason_code, count)
                for reason_code, count in (
                    (
                        reason,
                        sum(1 for e in events if e["event_type"] == "anomaly_flagged" and e.get("reason_code") == reason),
                    )
                    for reason in {e.get("reason_code") for e in events if e["event_type"] == "anomaly_flagged"}
                )
                if reason_code is not None
            ),
            key=lambda x: x[0],
        )
    )

    if vision_entries <= 0:
        entries = purchasers
        data_quality_flags.add("vision_unavailable_using_purchasers_as_baseline")
    else:
        entries = vision_entries
        if entries < purchasers:
            data_quality_flags.add("vision_undercount_detected")

    engaged_sessions = [
        s for s in sessions
        if events_by_session.get(s["session_id"], set())
        and s["total_amount"] > 0
    ]
    billing_sessions = [
        s for s in engaged_sessions
        if "transaction_linked" in events_by_session.get(s["session_id"], set())
        and s["item_count"] > 0
    ]

    engaged = len(engaged_sessions)
    billing_visitors = len(billing_sessions)

    if entries < purchasers:
        engaged = min(engaged, purchasers)
        billing_visitors = min(billing_visitors, purchasers)
        funnel_top = max(entries, purchasers)
    else:
        engaged = min(engaged, entries)
        billing_visitors = min(billing_visitors, engaged)
        purchasers = min(purchasers, billing_visitors)
        funnel_top = entries

    funnel_stages = [
        {"stage": "entries", "count": funnel_top},
        {"stage": "engaged_visitors", "count": engaged},
        {"stage": "billing_zone_visitors", "count": billing_visitors},
        {"stage": "purchasers", "count": purchasers},
    ]

    if funnel_top > 0:
        conversion_rate = round(purchasers / funnel_top, 4)
    else:
        conversion_rate = 0.0

    is_monotonic = all(
        funnel_stages[i]["count"] >= funnel_stages[i + 1]["count"]
        for i in range(len(funnel_stages) - 1)
    )

    metrics = {
        "generated_at": generated_at,
        "store_id": sessions[0]["store_id"] if sessions else "UNKNOWN",
        "entries": funnel_top,
        "purchasers": purchasers,
        "transactions": transactions,
        "conversion_rate": conversion_rate,
        "anomaly_count": anomaly_count,
        "data_quality_flags": sorted(data_quality_flags),
        "vision_processing_mode": vision_summary.get("processing_mode", "unknown"),
        "cameras_processed": int(vision_summary.get("cameras_processed", 0)),
        "vision_entry_events": int(vision_summary.get("entry_events", 0)),
        "vision_exit_events": int(vision_summary.get("exit_events", 0)),
        "staff_tracks_detected": int(vision_summary.get("staff_tracks_detected", 0)),
        "anomaly_reason_counts": anomaly_reason_counts,
        "vision_edge_case_signals": {
            "reentry_candidates": int(vision_summary.get("reentry_candidates", 0)),
            "group_crossing_candidates": int(vision_summary.get("group_crossing_candidates", 0)),
            "occlusion_candidates": int(vision_summary.get("occlusion_candidates", 0)),
        },
    }

    funnel = {
        "generated_at": generated_at,
        "stages": funnel_stages,
        "is_monotonic_non_increasing": is_monotonic,
    }

    return Snapshot(
        generated_at=generated_at,
        events=events,
        sessions=sessions,
        metrics=metrics,
        funnel=funnel,
    )



def persist_snapshot(config: AppConfig, snapshot: Snapshot) -> None:
    config.event_store.parent.mkdir(parents=True, exist_ok=True)

    with config.event_store.open("w", encoding="utf-8") as handle:
        for event in snapshot.events:
            handle.write(json.dumps(event) + "\n")

    with config.session_store.open("w", encoding="utf-8") as handle:
        json.dump(snapshot.sessions, handle, indent=2)

    with config.metrics_store.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "metrics": snapshot.metrics,
                "funnel": snapshot.funnel,
                "generated_at": snapshot.generated_at,
            },
            handle,
            indent=2,
        )
