from app.db.session import SessionLocal
from app.models.trip import Trip
from app.optimization.state import validate_trip_assignment, repair_trip_assignment, TripAssignmentStatus

db = SessionLocal()
try:
    trip = db.query(Trip).filter(Trip.route_id.isnot(None)).filter(Trip.vehicle_id.isnot(None)).first()
    print('trip:', trip.trip_id, 'route:', trip.route_id)
    print('before - validate:', validate_trip_assignment(db, trip).value)
    # Simulate the limbo state: strip resources in txn only
    trip.vehicle_id = None
    trip.driver_id = None
    db.flush()
    st = validate_trip_assignment(db, trip)
    print('after stripping - validate:', st.value)
    ok = repair_trip_assignment(db, trip)
    print('repair returned:', ok, '- vehicle:', trip.vehicle_id, '- driver:', trip.driver_id)
    print('after repair - validate:', validate_trip_assignment(db, trip).value)
finally:
    db.rollback(); db.close()