"""Regression suite for the optimization primitives (no DB writes).

Every check asserts the FIXED behavior; the suite fails if any of the
originally-found bugs reappears.
"""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failed = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        failed.append(name)


print("=" * 70)
print("CHECK 1: osrm_client.get_route_duration_hours is a proper coroutine")
from app.services.osrm_client import get_route_duration_hours
check("get_route_duration_hours async", inspect.iscoroutinefunction(get_route_duration_hours))

print("=" * 70)
print("CHECK 2: CostFunction._calculate_total_duration is sync-safe (no coroutine math)")
from app.optimization.scoring.cost_function import CostFunction
from app.models.route import RouteStop

cf = CostFunction()
stops = [
    RouteStop(latitude=51.9544, longitude=4.1241),
    RouteStop(latitude=52.0907, longitude=5.1214),
    RouteStop(latitude=52.3091, longitude=4.8933),
]
try:
    d = cf._calculate_total_duration(None, stops)
    check("total_duration sync-callable", isinstance(d, (int, float)), f"value={d}")
except Exception as exc:
    check("total_duration sync-callable", False, f"{type(exc).__name__}: {exc}")

print("=" * 70)
print("CHECK 3: FeasibilityEngine._check_capacity has no undefined 'db' reference")
from app.optimization.feasibility.engine import FeasibilityEngine, FeasibilityResult
from app.models.route import Route
from app.models.trip import Trip
from app.models.vehicle import Vehicle

fe = FeasibilityEngine()
r = FeasibilityResult(feasible=True, violations=[])
route = Route(stops=[RouteStop(trip_id="T1", stop_type="pickup", sequence=1)])
trip = Trip(trip_id="Tnew", load_weight_kg=100)
veh = Vehicle(vehicle_id="V1", load_capacity_kg=1000)
try:
    fe._check_capacity(route, trip, veh, r)
    check("_check_capacity no NameError", True)
except NameError as exc:
    check("_check_capacity no NameError", False, str(exc))
except Exception as exc:
    # Other exceptions (e.g. DB access) are out of scope for this unit check
    check("_check_capacity no NameError", True, f"(non-NameError: {type(exc).__name__})")

print("=" * 70)
print("CHECK 4: candidate_search imports the real Driver model (no string placeholder)")
import app.optimization.candidates.search as cs_mod
from app.models.driver import Driver as RealDriver

placeholder = getattr(cs_mod, "DriverMaster", None)
check("no 'DriverMaster' string placeholder", placeholder is None, repr(placeholder))
check("search module uses Driver model", cs_mod.Driver is RealDriver)

print("=" * 70)
print("CHECK 5: cost_function delay-risk tolerates missing driver attributes")
try:
    v = cf._calculate_delay_risk(None, route, trip)
    check("_calculate_delay_risk no AttributeError", isinstance(v, (int, float)), f"value={v}")
except AttributeError as exc:
    check("_calculate_delay_risk no AttributeError", False, str(exc))
except Exception as exc:
    check("_calculate_delay_risk no AttributeError", True, f"(non-AttributeError: {type(exc).__name__})")

print("=" * 70)
print("CHECK 6: async end-to-end OSRM duration call works")
async def _t():
    v = await get_route_duration_hours(51.9544, 4.1241, 52.0907, 5.1214)
    return v
try:
    v = asyncio.run(_t())
    check("async OSRM call", isinstance(v, (int, float)) and v > 0, f"hours={v}")
except Exception as exc:
    check("async OSRM call", False, f"{type(exc).__name__}: {exc}")

print()
if failed:
    print(f"=== UNIT CHECKS FAILED: {failed} ===")
    sys.exit(1)
print("=== ALL UNIT CHECKS PASSED ===")
