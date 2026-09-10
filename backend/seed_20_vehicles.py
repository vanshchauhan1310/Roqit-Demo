"""Seed 20 demo vehicles for the fleet.

Run (Docker):   docker compose exec backend python seed_20_vehicles.py
Run (local):    cd backend && python seed_20_vehicles.py
Idempotent:     existing IDs are skipped - safe to re-run.
"""
from app.db.session import SessionLocal
from app.models.vehicle import Vehicle

# (vehicle_id, type, make, model, year, fuel, capacity_kg, kmpl, base_location)
VEHICLES = [
    # Light Commercial Vehicles (1000-3000 kg)
    ("DEMO-V01", "Mini Truck", "Tata", "Ace Gold Pickup", 2023, "diesel", 1200, 20.0, "Hyderabad"),
    ("DEMO-V02", "Mini Truck", "Mahindra", "Supro Mini Truck", 2022, "diesel", 1500, 19.0, "Hyderabad"),
    ("DEMO-V03", "Mini Truck", "Maruti Suzuki", "Carry", 2023, "cng", 1000, 22.0, "Hyderabad"),
    ("DEMO-V04", "Mini Truck", "Tata", "Intra V10", 2024, "diesel", 1800, 18.5, "Hyderabad"),
    ("DEMO-V05", "Mini Truck", "Force", "Balwan 400", 2022, "diesel", 2000, 16.0, "Hyderabad"),
    # Medium Commercial Vehicles (3000-8000 kg)
    ("DEMO-V06", "Truck", "Tata", "Ultra T.14", 2023, "diesel", 4000, 14.0, "Hyderabad"),
    ("DEMO-V07", "Truck", "Ashok Leyland", "Dost Strong", 2022, "diesel", 3500, 15.0, "Hyderabad"),
    ("DEMO-V08", "Truck", "Eicher", "Pro 2080XP", 2023, "diesel", 5000, 12.0, "Hyderabad"),
    ("DEMO-V09", "Truck", "BharatBenz", "1217C", 2021, "diesel", 7000, 9.0, "Hyderabad"),
    ("DEMO-V10", "Truck", "Mahindra", "Furio 11", 2023, "diesel", 6000, 10.0, "Hyderabad"),
    ("DEMO-V11", "Truck", "Tata", "LPT 2518", 2022, "diesel", 8000, 8.0, "Hyderabad"),
    # Heavy Commercial Vehicles (8000-15000 kg)
    ("DEMO-V12", "Truck", "Ashok Leyland", "Captain 2523", 2023, "diesel", 9000, 7.5, "Hyderabad"),
    ("DEMO-V13", "Truck", "Tata", "Signa 4023", 2022, "diesel", 10000, 7.0, "Hyderabad"),
    ("DEMO-V14", "Container Truck", "Eicher", "Pro 6041", 2023, "diesel", 12000, 6.0, "Hyderabad"),
    ("DEMO-V15", "Container Truck", "BharatBenz", "2523R", 2021, "diesel", 14000, 5.5, "Hyderabad"),
    ("DEMO-V16", "Truck", "Ashok Leyland", "Ecomet 1615", 2024, "diesel", 11000, 6.5, "Hyderabad"),
    # Refrigerated Trucks
    ("DEMO-V17", "Refrigerated Truck", "Tata", "Ultra 1918 Refri", 2023, "diesel", 5000, 10.0, "Hyderabad"),
    ("DEMO-V18", "Refrigerated Truck", "Mahindra", "Blazo X 35 Refri", 2022, "diesel", 8000, 8.0, "Hyderabad"),
    # Heavy Trailers (15000+ kg)
    ("DEMO-V19", "Trailer", "Tata", "Signa 5530.S", 2023, "diesel", 25000, 4.0, "Hyderabad"),
    ("DEMO-V20", "Trailer", "Ashok Leyland", "AVTR 5525 HT", 2022, "diesel", 30000, 3.5, "Hyderabad"),
]


def seed() -> None:
    db = SessionLocal()
    try:
        added = 0
        for vid, vtype, make, model, year, fuel, cap, kmpl, base in VEHICLES:
            if db.get(Vehicle, vid):
                continue
            db.add(Vehicle(
                vehicle_id=vid, vehicle_type=vtype, make=make, model=model,
                year=year, fuel_type=fuel, load_capacity_kg=cap,
                avg_kmpl_rated=kmpl, base_location=base, status="active",
            ))
            added += 1
        db.commit()
        total = db.query(Vehicle).count()
        print(f"[seed] added {added} vehicle(s). Fleet now: {total} vehicles total.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
