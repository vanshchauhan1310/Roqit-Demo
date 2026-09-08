"""Seed a demo fleet (vehicles + drivers) so the assignment engine has resources.

The Live Ops auto-feed generates Hyderabad trips with vehicle_type="Truck" and
200-1400 kg loads; the greedy engine needs active, compatible vehicles and
drivers to assign them - without any, every trip lands in the unassigned queue
("No available vehicle / driver").

Run (Docker):   docker compose exec backend python seed_fleet.py
Run (local):    cd backend && python seed_fleet.py
Idempotent:     existing IDs are skipped - safe to re-run.
"""
from app.db.session import SessionLocal
from app.models.vehicle import Vehicle
from app.models.driver import Driver

# (vehicle_id, type, make, model, year, fuel, capacity_kg, kmpl, base_location)
VEHICLES = [
    # fuel_type values must match the ML feature contract's Literal["CNG", "Diesel"]
    # exactly - lowercase "diesel" makes every delay/cost prediction fail with
    # UnsupportedCategoryError (see delay_prediction_service._check_vocabulary).
    ("VEH001", "Truck", "Tata", "Ace Gold", 2022, "Diesel", 2000, 18.0, "Hyderabad"),
    ("VEH002", "Truck", "Mahindra", "Bolero Maxx", 2021, "Diesel", 3500, 16.0, "Hyderabad"),
    ("VEH003", "Truck", "Ashok Leyland", "Dost+", 2023, "Diesel", 3000, 17.0, "Hyderabad"),
    ("VEH004", "Truck", "Eicher", "Pro 2049", 2022, "Diesel", 6000, 12.0, "Hyderabad"),
    ("VEH005", "Truck", "Tata", "Ultra 1918", 2021, "Diesel", 9000, 8.5, "Hyderabad"),
    ("VEH006", "Truck", "BharatBenz", "1917C", 2020, "Diesel", 12000, 6.5, "Hyderabad"),
    ("VEH007", "Truck", "Ashok Leyland", "Boss 1920", 2023, "Diesel", 14000, 6.0, "Hyderabad"),
    ("VEH008", "Truck", "Tata", "Signa 4825", 2022, "Diesel", 16000, 5.0, "Hyderabad"),
    # Non-Truck types for realism; the auto-feed only books Trucks.
    ("VEH101", "Tempo", "Force", "Trax Cargo", 2022, "Diesel", 1200, 19.0, "Hyderabad"),
    ("VEH102", "Trailer", "Tata", "Signa 5525", 2021, "Diesel", 25000, 4.0, "Hyderabad"),
]

# (driver_id, name, phone, license, expiry, joined, exp_years, base, rating)
DRIVERS = [
    ("DRV001", "Ravi Kumar", 9848012301, "HMV", "2027-05-14", "2019-03-01", 8.0, "Hyderabad", 4.6),
    ("DRV002", "Suresh Reddy", 9848012302, "HMV", "2026-11-02", "2017-08-15", 10.0, "Hyderabad", 4.8),
    ("DRV003", "Imran Khan", 9848012303, "HMV", "2027-01-20", "2021-06-10", 5.0, "Hyderabad", 4.2),
    ("DRV004", "Prakash Rao", 9848012304, "HMV", "2028-03-30", "2015-01-05", 12.0, "Hyderabad", 4.9),
    ("DRV005", "Venkat Yadav", 9848012305, "HMV", "2026-09-18", "2022-02-20", 3.5, "Hyderabad", 3.9),
    ("DRV006", "Mohan Sai", 9848012306, "HMV", "2027-08-07", "2020-11-11", 6.5, "Hyderabad", 4.4),
]


def seed() -> None:
    db = SessionLocal()
    try:
        added_v = added_d = 0
        for vid, vtype, make, model, year, fuel, cap, kmpl, base in VEHICLES:
            if db.get(Vehicle, vid):
                continue
            db.add(Vehicle(
                vehicle_id=vid, vehicle_type=vtype, make=make, model=model,
                year=year, fuel_type=fuel, load_capacity_kg=cap,
                avg_kmpl_rated=kmpl, base_location=base, status="active",
            ))
            added_v += 1
        for did, name, phone, lic, expiry, joined, exp, base, rating in DRIVERS:
            if db.get(Driver, did):
                continue
            db.add(Driver(
                driver_id=did, driver_name=name, phone=phone, license_type=lic,
                license_expiry=expiry, date_joined=joined, experience_years=exp,
                base_location=base, rating=rating, status="active",
            ))
            added_d += 1
        db.commit()
        n_v = db.query(Vehicle).count()
        n_d = db.query(Driver).count()
        print(f"[seed] added {added_v} vehicle(s), {added_d} driver(s). "
              f"Fleet now: {n_v} vehicles, {n_d} drivers.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
