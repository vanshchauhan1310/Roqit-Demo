"""Seeds hubs, vehicle/driver cost rates, and fuel prices for LOCAL TESTING.

!! THE NUMBERS BELOW ARE NOT PRODUCTION VALUES. !!
They exist so the fleet optimizer can be exercised end-to-end against a real
database. Replace every rate with figures the business actually stands behind
before any of this informs a real dispatch decision.

Idempotent: re-running updates the same rows rather than duplicating them.
Vehicle/driver rows are only written for IDs that already exist in
vehicle_master / driver_master - this script never invents fleet members.

Usage, from backend/ with its venv active:
    python seed_dispatch_config.py
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.dispatch_config import DriverDispatchConfig, FuelPrice, VehicleDispatchConfig
from app.models.driver import Driver
from app.models.hub import Hub
from app.models.vehicle import Vehicle

# Approximate city-centre coordinates - placeholders for real depot locations.
HUBS = [
    {"name": "Hyderabad Central", "latitude": 17.3850, "longitude": 78.4867, "hub_type": "DEPOT"},
    {"name": "Delhi Central", "latitude": 28.6139, "longitude": 77.2090, "hub_type": "DEPOT"},
    {"name": "Chennai Central", "latitude": 13.0827, "longitude": 80.2707, "hub_type": "DEPOT"},
]

FUEL_PRICES = [
    {"fuel_type": "Diesel", "price_per_liter": 95.0},
    {"fuel_type": "CNG", "price_per_liter": 78.0},
]

# Applied to however many real vehicles exist, in id order.
VEHICLE_RATE_PROFILES = [
    {"fixed_route_cost": 400.0, "cost_per_km": 8.0},
    {"fixed_route_cost": 800.0, "cost_per_km": 12.0},
    {"fixed_route_cost": 1200.0, "cost_per_km": 15.0},
]
DRIVER_HOURLY_RATES = [150.0, 180.0, 165.0]


def seed() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        hubs: list[Hub] = []
        for spec in HUBS:
            hub = db.execute(select(Hub).where(Hub.name == spec["name"])).scalar_one_or_none()
            if hub is None:
                hub = Hub(hub_id=uuid.uuid4(), **spec)
                db.add(hub)
            else:
                for k, v in spec.items():
                    setattr(hub, k, v)
            hubs.append(hub)
        db.flush()
        print(f"hubs: {len(hubs)} ({', '.join(h.name for h in hubs)})")

        for spec in FUEL_PRICES:
            existing = db.execute(
                select(FuelPrice).where(
                    FuelPrice.fuel_type == spec["fuel_type"], FuelPrice.effective_to.is_(None)
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(FuelPrice(fuel_price_id=uuid.uuid4(), effective_from=now, **spec))
            else:
                existing.price_per_liter = spec["price_per_liter"]
        print(f"fuel prices: {len(FUEL_PRICES)}")

        # Every fleet vehicle needs a depot for hub-anchored planning. Prefer
        # its imported base city over arbitrary row rotation: a Hyderabad
        # vehicle must leave and return to Hyderabad; likewise for Delhi.
        # The round-robin fallback is only for records with no matching city.
        vehicles = db.execute(select(Vehicle).order_by(Vehicle.vehicle_id)).scalars().all()
        for i, vehicle in enumerate(vehicles):
            profile = VEHICLE_RATE_PROFILES[i % len(VEHICLE_RATE_PROFILES)]
            location = (vehicle.base_location or "").casefold()
            matching_hubs = [hub for hub in hubs if (hub.name or "").casefold().split()[0] in location]
            hub = matching_hubs[0] if len(matching_hubs) == 1 else hubs[i % len(hubs)]
            config = db.get(VehicleDispatchConfig, vehicle.vehicle_id)
            if config is None:
                config = VehicleDispatchConfig(vehicle_id=vehicle.vehicle_id)
                db.add(config)
            config.base_hub_id = hub.hub_id
            config.end_hub_id = None  # returns to base
            config.fixed_route_cost = profile["fixed_route_cost"]
            config.cost_per_km = profile["cost_per_km"]
        print(f"vehicle dispatch configs: {len(vehicles)}")

        # Keep the local/demo dispatch configuration internally complete.  A
        # partial first-N seed makes otherwise available vehicles fail fleet
        # costing simply because their assigned driver's rate row was skipped.
        # These remain documented placeholder rates and must not be used as a
        # substitute for approved production cost data.
        drivers = db.execute(select(Driver).order_by(Driver.driver_id)).scalars().all()
        for i, driver in enumerate(drivers):
            config = db.get(DriverDispatchConfig, driver.driver_id)
            if config is None:
                config = DriverDispatchConfig(driver_id=driver.driver_id)
                db.add(config)
            config.cost_per_hour = DRIVER_HOURLY_RATES[i % len(DRIVER_HOURLY_RATES)]
        print(f"driver dispatch configs: {len(drivers)}")

        db.commit()
        print("\nSeeded. Remember: these rates are placeholders, not production values.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
