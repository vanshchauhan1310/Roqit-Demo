from app.db.session import SessionLocal
from app.models.route import Route, RouteStop
from sqlalchemy import func
db = SessionLocal()
routes = db.query(Route).limit(3).all()
route_ids = [r.route_id for r in routes]
print("route_ids:", route_ids)
from app.models.trip import Trip
from app.models.delay_prediction import DelayPrediction
stats = (db.query(RouteStop.route_id.label("route_id"), func.count(DelayPrediction.prediction_id).label("count")).join(Trip, Trip.trip_id == RouteStop.trip_id).join(DelayPrediction, DelayPrediction.trip_id == Trip.trip_id).filter(RouteStop.route_id.in_(route_ids)).group_by(RouteStop.route_id).all())
print("stats:", stats)
rs = db.query(RouteStop.route_id).first()
print("route_stops route_id type:", type(rs[0]), rs[0])
raw = db.execute(func.count(DelayPrediction.prediction_id)).scalar()
print("total predictions:", raw)
db.close()
