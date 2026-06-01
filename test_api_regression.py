from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Any


@dataclass
class VisionConfig:
    frame_stride: int = 10
    max_frames_per_camera: int = 600
    min_contour_area: int = 600
    staff_min_visible_seconds: float = 25.0
    max_seconds_per_camera: float = 20.0


def _camera_id_from_path(video_path: Path) -> str:
    return video_path.stem.upper().replace(" ", "_")


def _ts_from_offset(base_time: datetime, offset_seconds: float) -> str:
    ts = base_time + timedelta(seconds=offset_seconds)
    return ts.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _make_event(
    event_id: str,
    event_type: str,
    event_time: str,
    store_id: str,
    camera_id: str,
    session_id: str,
    confidence: float,
    dedupe_key: str,
    reason_code: str,
    source: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_time": event_time,
        "store_id": store_id,
        "camera_id": camera_id,
        "zone_id": "entry_gate",
        "session_id": session_id,
        "order_id": None,
        "customer_number": None,
        "confidence": confidence,
        "dedupe_key": dedupe_key,
        "reason_code": reason_code,
        "source": source,
    }


class _SimpleTracker:
    def __init__(self, max_distance: int = 65, max_missed: int = 20):
        self.max_distance = max_distance
        self.max_missed = max_missed
        self.next_id = 1
        self.objects: dict[int, dict[str, Any]] = {}

    @staticmethod
    def _distance(a: tuple[int, int], b: tuple[int, int]) -> float:
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        return (dx * dx + dy * dy) ** 0.5

    def update(self, centers: list[tuple[int, int]], timestamp_s: float, in_counter_zone: list[bool]) -> dict[int, dict[str, Any]]:
        assigned: set[int] = set()

        for center, counter_flag in zip(centers, in_counter_zone):
            best_id = None
            best_dist = float("inf")

            for obj_id, obj in self.objects.items():
                if obj_id in assigned:
                    continue
                dist = self._distance(obj["center"], center)
                if dist < best_dist and dist <= self.max_distance:
                    best_dist = dist
                    best_id = obj_id

            if best_id is None:
                obj_id = self.next_id
                self.next_id += 1
                self.objects[obj_id] = {
                    "center": center,
                    "prev_center": center,
                    "first_seen_s": timestamp_s,
                    "last_seen_s": timestamp_s,
                    "missed": 0,
                    "counter_hits": 1 if counter_flag else 0,
                    "samples": 1,
                    "is_staff": False,
                    "entry_count": 0,
                    "exit_count": 0,
                    "last_cross_s": None,
                    "last_cross": None,
                }
                assigned.add(obj_id)
            else:
                obj = self.objects[best_id]
                obj["prev_center"] = obj["center"]
                obj["center"] = center
                obj["last_seen_s"] = timestamp_s
                obj["missed"] = 0
                obj["samples"] += 1
                if counter_flag:
                    obj["counter_hits"] += 1
                assigned.add(best_id)

        for obj_id, obj in list(self.objects.items()):
            if obj_id not in assigned:
                obj["missed"] += 1
                if obj["missed"] > self.max_missed:
                    del self.objects[obj_id]
                    continue

            visible_seconds = obj["last_seen_s"] - obj["first_seen_s"]
            counter_ratio = obj["counter_hits"] / max(1, obj["samples"])
            if visible_seconds >= 25.0 and counter_ratio >= 0.5:
                obj["is_staff"] = True

        return self.objects



def extract_vision_events(video_dir: Path, store_id: str, cfg: VisionConfig | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    cfg = cfg or VisionConfig()
    flags: list[str] = []

    try:
        import cv2  # type: ignore
    except Exception:
        return [], {
            "processing_mode": "no_cv2",
            "cameras_processed": 0,
            "entry_events": 0,
            "exit_events": 0,
            "staff_tracks_detected": 0,
        }, ["opencv_unavailable"]

    video_files = sorted(video_dir.glob("*.mp4"))
    if not video_files:
        return [], {
            "processing_mode": "no_videos",
            "cameras_processed": 0,
            "entry_events": 0,
            "exit_events": 0,
            "staff_tracks_detected": 0,
        }, ["no_video_files_detected"]

    source = "cctv_motion_tracker_v1"
    all_events: list[dict[str, Any]] = []
    total_entry = 0
    total_exit = 0
    total_staff_tracks = 0
    total_reentry_candidates = 0
    total_group_crossing_candidates = 0
    total_occlusion_candidates = 0
    cameras_processed = 0

    base_time = datetime(2026, 4, 10, 9, 0, 0, tzinfo=timezone.utc)

    for video_path in video_files:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            flags.append(f"camera_open_failed:{video_path.name}")
            continue

        cameras_processed += 1
        camera_id = _camera_id_from_path(video_path)

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = 25.0

        back_sub = cv2.createBackgroundSubtractorMOG2(history=250, varThreshold=24, detectShadows=True)
        tracker = _SimpleTracker()

        line_y = None
        frame_idx = 0
        processed_frames = 0
        started_at = monotonic()

        while processed_frames < cfg.max_frames_per_camera:
            if (monotonic() - started_at) >= cfg.max_seconds_per_camera:
                flags.append(f"camera_timeout:{video_path.name}")
                break
            ok, frame = cap.read()
            if not ok:
                break

            frame_idx += 1
            if frame_idx % cfg.frame_stride != 0:
                continue

            processed_frames += 1
            h, w = frame.shape[:2]
            if line_y is None:
                line_y = int(h * 0.55)

            fg = back_sub.apply(frame)
            _, thresh = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

            contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            centers: list[tuple[int, int]] = []
            in_counter_zone: list[bool] = []
            large_blob_count = 0

            for contour in contours:
                area = cv2.contourArea(contour)
                if area < cfg.min_contour_area:
                    continue
                if area >= (cfg.min_contour_area * 10):
                    large_blob_count += 1

                x, y, ww, hh = cv2.boundingRect(contour)
                cx = x + (ww // 2)
                cy = y + (hh // 2)

                centers.append((cx, cy))
                near_counter = cx >= int(w * 0.7) and cy >= int(h * 0.35)
                in_counter_zone.append(near_counter)

            if line_y is not None and centers:
                near_line_count = sum(1 for _, cy in centers if abs(cy - line_y) <= int(h * 0.05))
                if near_line_count >= 3:
                    total_group_crossing_candidates += 1
            if large_blob_count > 0 and len(centers) <= 1:
                total_occlusion_candidates += large_blob_count

            timestamp_s = frame_idx / fps
            objects = tracker.update(centers, timestamp_s, in_counter_zone)

            for obj_id, obj in objects.items():
                if obj.get("missed", 0) != 0:
                    continue
                if line_y is None:
                    continue

                prev_y = obj["prev_center"][1]
                curr_y = obj["center"][1]

                crossed_entry = prev_y < line_y <= curr_y
                crossed_exit = prev_y > line_y >= curr_y

                if not crossed_entry and not crossed_exit:
                    continue

                ev_time = _ts_from_offset(base_time, timestamp_s)
                session_id = f"VIS_{camera_id}_{obj_id}"
                is_staff = obj.get("is_staff", False)

                if crossed_entry:
                    is_reentry_candidate = (
                        obj.get("last_cross") == "exit"
                        and obj.get("last_cross_s") is not None
                        and (timestamp_s - float(obj["last_cross_s"])) <= 120.0
                    )
                    obj["entry_count"] += 1
                    obj["last_cross"] = "entry"
                    obj["last_cross_s"] = timestamp_s
                    reason = "tripwire_crossing"
                    conf = 0.72 if not is_staff else 0.58
                    if is_staff:
                        reason = "staff_filtered_crossing"
                    elif is_reentry_candidate:
                        reason = "reentry_candidate_tripwire"
                        total_reentry_candidates += 1
                    event = _make_event(
                        event_id=f"EV_{camera_id}_{obj_id}_{int(timestamp_s * 10)}_ENTRY",
                        event_type="entry_confirmed" if not is_staff else "staff_movement",
                        event_time=ev_time,
                        store_id=store_id,
                        camera_id=camera_id,
                        session_id=session_id,
                        confidence=conf,
                        dedupe_key=f"{camera_id}:{obj_id}:entry:{int(timestamp_s)}",
                        reason_code=reason,
                        source=source,
                    )
                    all_events.append(event)
                    if not is_staff:
                        total_entry += 1

                if crossed_exit:
                    is_reentry_candidate = (
                        obj.get("last_cross") == "entry"
                        and obj.get("last_cross_s") is not None
                        and (timestamp_s - float(obj["last_cross_s"])) <= 120.0
                    )
                    obj["exit_count"] += 1
                    obj["last_cross"] = "exit"
                    obj["last_cross_s"] = timestamp_s
                    reason = "tripwire_crossing"
                    conf = 0.7 if not is_staff else 0.58
                    if is_staff:
                        reason = "staff_filtered_crossing"
                    elif is_reentry_candidate:
                        reason = "reentry_candidate_tripwire"
                        total_reentry_candidates += 1
                    event = _make_event(
                        event_id=f"EV_{camera_id}_{obj_id}_{int(timestamp_s * 10)}_EXIT",
                        event_type="exit_confirmed" if not is_staff else "staff_movement",
                        event_time=ev_time,
                        store_id=store_id,
                        camera_id=camera_id,
                        session_id=session_id,
                        confidence=conf,
                        dedupe_key=f"{camera_id}:{obj_id}:exit:{int(timestamp_s)}",
                        reason_code=reason,
                        source=source,
                    )
                    all_events.append(event)
                    if not is_staff:
                        total_exit += 1

        total_staff_tracks += sum(1 for obj in tracker.objects.values() if obj.get("is_staff"))
        cap.release()

    summary = {
        "processing_mode": "motion_tripwire",
        "cameras_processed": cameras_processed,
        "entry_events": total_entry,
        "exit_events": total_exit,
        "staff_tracks_detected": total_staff_tracks,
        "reentry_candidates": total_reentry_candidates,
        "group_crossing_candidates": total_group_crossing_candidates,
        "occlusion_candidates": total_occlusion_candidates,
    }

    return all_events, summary, flags
