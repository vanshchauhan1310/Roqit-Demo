"""Post-fix verification of the optimization primitives."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("1) sync OSRM client works")
from app.services.osrm_client import get_route_duration_hours_sync, get_route_duration_hours
import inspect
assert not inspect.iscoroutinefunction(get_route_duration_hours_sync)
v = get_route_duration_hours_sync(51.9544, 4.1241, 52.0907, 5.1214)
print("   sync OSRM duration hours:", v)

print("=" * 60)
print("2) CostFunction duration no longer crashes (sync client)")
from app.optimization.scoring.cost_function import CostFunction
from app.models.route import RouteStop
cf = CostFunction()
stops = [
    RouteStop(latitude=51.9544, longitude=4.1241, sequence=1),
    RouteStop(latitude=52.0907, longitude=5.1214, sequence=2),
    RouteStop(latitude=52.3091, longitude=4.8933, sequence=3),
]
dur = cf._calculate_total_duration(None, stops)
print("   total_duration_sec:", dur)
assert dur > 0

print("=" * 60)
print("3) FeasibilityEngine._check_capacity with db arg does not crash")
from app.optimization.feasibility.engine import FeasibilityEngine, FeasibilityResult
from app.db.session import SessionLocal
from app.models.route import Route
from app.models.trip import Trip
from app.models.vehicle import Vehicle

db = SessionLocal()
try:
    fe = FeasibilityEngine()
    res = FeasibilityResult(feasible=True, violations=[])
    route = Route(stops=[RouteStop(trip_id="T1", stop_type="pickup", sequence=1)])
    trip = Trip(trip_id="Tnew", load_weight_kg=100)
    veh = Vehicle(vehicle_id="V1", load_capacity_kg=5000)
    fe._check_capacity(db, route, trip, veh, res)
    print("   capacity check ok, feasible =", res.feasible)
finally:
    db.close()

print("=" * 60)
print("4) CandidateSearch imports real Driver class")
from app.optimization.candidates.search import CandidateSearch, CandidateRoute
import app.optimization.candidates.search as m
print("   Driver:", m.Driver.__name__)
cs = CandidateSearch()
assert cs.max_candidates == 50

print("=" * 60)
print("5) CostFunction delay risk (rating proxy) does not crash")
from app.models.driver import Driver
route = Route(driver_id="D1")
route.driver = Driver(driver_id="D1", rating=4.5)
trip = Trip(trip_id="T1", traffic_density="Low", weather_condition="Clear")
risk = cf._calculate_delay_risk(route, trip)
print("   delay_risk:", risk)
assert 0.0 <= risk <= 1.0

print("\nALL UNIT VERIFICATIONS PASSED")