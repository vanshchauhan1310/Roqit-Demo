"""Contract tests for explicit fleet split-load assignments.

These tests stay at the backend boundary: the solver receives only reconciled,
capacity-checkable jobs and never gets an opportunity to replace a trip's
recorded weight with a smaller part weight.
"""

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.optimize import OptimizeStopInput  # noqa: E402
from app.services.route_optimizer import _build_jobs  # noqa: E402


def _stop(key: str, trip_id: str, stop_type: str, **kwargs) -> OptimizeStopInput:
    return OptimizeStopInput(key=key, latitude=17.0, longitude=78.0, trip_id=trip_id, stop_type=stop_type, **kwargs)


def test_unequal_split_preserves_the_original_trip_weight():
    """25,000 kg is represented as two assignments, never reduced to either part."""
    jobs = _build_jobs([
        _stop("trip:1:p", "TRIP part 1/2", "pickup", load_weight_kg=18_000, assigned_weight_kg=18_000,
              parent_trip_id="TRIP", original_load_weight_kg=25_000, allowed_vehicle_ids=["VEH008"], allow_split_loads=True),
        _stop("trip:1:d", "TRIP part 1/2", "delivery"),
        _stop("trip:2:p", "TRIP part 2/2", "pickup", load_weight_kg=7_000, assigned_weight_kg=7_000,
              parent_trip_id="TRIP", original_load_weight_kg=25_000, allowed_vehicle_ids=["VEH016"], allow_split_loads=True),
        _stop("trip:2:d", "TRIP part 2/2", "delivery"),
    ])

    assert sum(job["load_weight_kg"] for job in jobs) == 25_000
    assert {job["original_load_weight_kg"] for job in jobs} == {25_000}
    assert [job["allowed_vehicle_ids"] for job in jobs] == [["VEH008"], ["VEH016"]]


def test_indivisible_trip_cannot_be_silently_split():
    stops = [
        _stop("trip:1:p", "TRIP part 1/2", "pickup", load_weight_kg=18_000,
              parent_trip_id="TRIP", original_load_weight_kg=25_000),
        _stop("trip:1:d", "TRIP part 1/2", "delivery"),
        _stop("trip:2:p", "TRIP part 2/2", "pickup", load_weight_kg=7_000,
              parent_trip_id="TRIP", original_load_weight_kg=25_000),
        _stop("trip:2:d", "TRIP part 2/2", "delivery"),
    ]

    with pytest.raises(HTTPException, match="does not allow split loads"):
        _build_jobs(stops)


def test_assignment_weight_cannot_conflict_with_the_load_weight():
    stops = [
        _stop("trip:p", "TRIP", "pickup", load_weight_kg=25_000, assigned_weight_kg=18_000),
        _stop("trip:d", "TRIP", "delivery"),
    ]

    with pytest.raises(HTTPException, match="conflicting assigned and load weights"):
        _build_jobs(stops)
