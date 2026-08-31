"""Wire ML ETA predictions to auto-generate time windows for optimizer."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from src.models import eta_prediction
from src.optimizer import opt

BUFFER_SECONDS = 15 * 60  # ±15 min window around ML ETA
DEFAULT_SPEED_KPH = 40.0
DEFAULT_SERVICE_SEC = 300


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def estimate_leg_duration_minutes(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    start_ts: int,
    avg_speed_kph: float = DEFAULT_SPEED_KPH,
) -> float:
    """Call ML ETA model for a single leg. Falls back to haversine/speed if model missing."""
    dist_km = haversine_km(from_lat, from_lon, to_lat, to_lon)
    dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)

    payload = {
        "distance_km": dist_km,
        "num_stops": 2,
        "hour_of_day": dt.hour,
        "day_of_week": dt.weekday(),
        "avg_historical_speed_kph": avg_speed_kph,
    }

    try:
        return eta_prediction.predict(payload)
    except FileNotFoundError:
        # Fallback: distance / speed
        return (dist_km / avg_speed_kph) * 60


def build_time_windows_for_jobs(
    jobs: list[opt.Job],
    coordinates: list[tuple[float, float]],
    start_ts: int,
    vehicle_speed_kph: float = DEFAULT_SPEED_KPH,
    buffer_seconds: int = BUFFER_SECONDS,
    service_time_sec: int = DEFAULT_SERVICE_SEC,
) -> tuple[list[opt.Job], int]:
    """
    For each job, predict pickup and delivery ETAs using ML model,
    convert to time windows, attach to Job objects.

    Returns (updated_jobs, current_time_after_last_job).
    """
    updated = []
    current_time = start_ts
    prev_delivery_lat = None
    prev_delivery_lon = None

    for job in jobs:
        pickup_lat, pickup_lon = coordinates[job.pickup_idx]
        delivery_lat, delivery_lon = coordinates[job.delivery_idx]

        # Predict travel to pickup
        if current_time == start_ts:
            # First job: from depot (first coordinate)
            depot_lat, depot_lon = coordinates[0]
            from_lat, from_lon = depot_lat, depot_lon
        else:
            # From previous delivery
            from_lat, from_lon = prev_delivery_lat, prev_delivery_lon

        to_pickup_min = estimate_leg_duration_minutes(
            from_lat, from_lon, pickup_lat, pickup_lon, current_time, vehicle_speed_kph
        )
        pickup_eta_ts = current_time + int(to_pickup_min * 60)

        # Predict pickup -> delivery leg
        trip_min = estimate_leg_duration_minutes(
            pickup_lat, pickup_lon, delivery_lat, delivery_lon, pickup_eta_ts, vehicle_speed_kph
        )
        delivery_eta_ts = pickup_eta_ts + int(trip_min * 60)

        # Attach windows
        job.pickup_earliest = pickup_eta_ts - buffer_seconds
        job.pickup_latest = pickup_eta_ts + buffer_seconds
        job.delivery_earliest = delivery_eta_ts - buffer_seconds
        job.delivery_latest = delivery_eta_ts + buffer_seconds
        job.service_time_sec = service_time_sec

        updated.append(job)

        # Advance for next iteration
        current_time = delivery_eta_ts + service_time_sec
        prev_delivery_lat, prev_delivery_lon = delivery_lat, delivery_lon

    return updated, current_time


def optimize_with_ml_windows(
    jobs: list[opt.Job],
    duration_matrix: opt.Matrix,
    distance_matrix: opt.Matrix,
    coordinates: list[tuple[float, float]],
    vehicle_capacity_kg: float | None,
    start_ts: int,
    vehicle_speed_kph: float = DEFAULT_SPEED_KPH,
) -> opt.SolveResult:
    """
    High-level function: enrich jobs with ML-predicted windows, then solve.
    """
    # Enrich jobs with time windows from ML ETA
    enriched_jobs, _ = build_time_windows_for_jobs(
        jobs, coordinates, start_ts, vehicle_speed_kph
    )

    # Solve with time-aware optimizer
    return opt.solve(
        enriched_jobs,
        duration_matrix,
        distance_matrix,
        vehicle_capacity_kg,
        start_time=start_ts,
    )