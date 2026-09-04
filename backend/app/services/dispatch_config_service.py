"""Resolves the real hub + cost-rate configuration the fleet optimizer needs.

The single rule this module exists to enforce: a rate that isn't configured is
reported as MISSING, never substituted with 0. A zero cost_per_km is a real
business statement ("this vehicle costs nothing per km"); an absent one means
nobody has told us, and costing it at zero would make that vehicle look free and
bias every assignment toward it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dispatch_config import DriverDispatchConfig, FuelPrice, VehicleDispatchConfig
from app.models.driver import Driver
from app.models.hub import Hub
from app.models.vehicle import Vehicle


# Baseline dispatch rates for drivers imported without an app-owned cost row.
# These match backend/seed_dispatch_config.py and are only used to fill a
# missing value; an approved configured rate is never overwritten.
DEFAULT_DRIVER_HOURLY_RATES = (150.0, 180.0, 165.0)


@dataclass
class ResolvedVehicleConfig:
    """Everything the optimizer needs about one vehicle, with provenance for
    whatever couldn't be resolved."""

    vehicle_id: str
    capacity_kg: float | None = None
    avg_kmpl_rated: float | None = None
    fuel_type: str | None = None
    fuel_price_per_l: float | None = None
    fixed_route_cost: float | None = None
    cost_per_km: float | None = None
    start_hub: Hub | None = None
    end_hub: Hub | None = None
    missing: list[str] = field(default_factory=list)

    @property
    def can_cost_fuel(self) -> bool:
        return self.avg_kmpl_rated is not None and self.avg_kmpl_rated > 0 and self.fuel_price_per_l is not None

    @property
    def is_fully_costed(self) -> bool:
        """True when every monetary component of this vehicle's cost is known,
        which is what lets the response claim cost_is_monetary."""
        return self.can_cost_fuel and self.cost_per_km is not None and self.fixed_route_cost is not None


def _normalise_location(value: str | None) -> str:
    """Make free-text city labels comparable without pretending they are GPS data."""
    return "".join(character for character in (value or "").casefold() if character.isalnum())


def _hub_for_vehicle_location(db: Session, location: str | None) -> Hub | None:
    """Resolve a vehicle's city (for example ``Hyderabad``) to its depot.

    The imported vehicle master uses a free-text ``base_location`` while hubs
    carry the coordinates required by OSRM.  A containment match supports hub
    labels such as "Hyderabad Central" and "Delhi Depot".  Ambiguous or empty
    values intentionally return None so the explicit dispatch configuration
    remains the safe fallback.
    """
    city = _normalise_location(location)
    if not city:
        return None
    matches = [
        hub for hub in db.execute(select(Hub).where(Hub.is_active.is_(True))).scalars()
        if city in _normalise_location(hub.name)
        or city in _normalise_location(hub.address)
        or _normalise_location(hub.name) in city
    ]
    return matches[0] if len(matches) == 1 else None


def current_fuel_price(db: Session, fuel_type: str | None, at: datetime | None = None) -> float | None:
    """Effective-dated lookup: the newest row for this fuel type whose window
    covers `at`. Returns None (not a default) when nothing is configured."""
    if not fuel_type:
        return None
    at = at or datetime.now(timezone.utc)
    row = db.execute(
        select(FuelPrice)
        .where(
            FuelPrice.fuel_type == fuel_type,
            FuelPrice.effective_from <= at,
            (FuelPrice.effective_to.is_(None)) | (FuelPrice.effective_to > at),
        )
        .order_by(FuelPrice.effective_from.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row.price_per_liter if row else None


def resolve_vehicle_config(db: Session, vehicle_id: str, require_hub: bool = False) -> ResolvedVehicleConfig:
    """Joins vehicle_master (capacity/mileage/fuel type, CSV-imported) with
    vehicle_dispatch_config (hub + cost rates, app-owned) into one view."""
    vehicle = db.get(Vehicle, vehicle_id)
    resolved = ResolvedVehicleConfig(vehicle_id=vehicle_id)

    if vehicle is None:
        resolved.missing.append(f"vehicle {vehicle_id} not found")
        return resolved

    resolved.capacity_kg = float(vehicle.load_capacity_kg) if vehicle.load_capacity_kg is not None else None
    resolved.avg_kmpl_rated = vehicle.avg_kmpl_rated
    resolved.fuel_type = vehicle.fuel_type

    if resolved.capacity_kg is None:
        resolved.missing.append(f"{vehicle_id}: load_capacity_kg")
    if resolved.avg_kmpl_rated is None:
        resolved.missing.append(f"{vehicle_id}: avg_kmpl_rated")

    resolved.fuel_price_per_l = current_fuel_price(db, vehicle.fuel_type)
    if resolved.fuel_price_per_l is None:
        resolved.missing.append(f"{vehicle_id}: fuel price for {vehicle.fuel_type or 'unknown fuel type'}")

    # A known base-city hub is usable even if rate configuration has not yet
    # been entered. Cost validation can then report the real missing rates
    # instead of incorrectly claiming that the vehicle has no starting point.
    location_hub = _hub_for_vehicle_location(db, vehicle.base_location)
    if location_hub is not None:
        resolved.start_hub = location_hub
        resolved.end_hub = location_hub

    config = db.get(VehicleDispatchConfig, vehicle_id)
    if config is None:
        resolved.missing.append(f"{vehicle_id}: no dispatch config (cost rates, hub)")
        if require_hub and resolved.start_hub is None:
            resolved.missing.append(f"{vehicle_id}: base hub")
        return resolved

    resolved.fixed_route_cost = config.fixed_route_cost
    resolved.cost_per_km = config.cost_per_km
    if config.fixed_route_cost is None:
        resolved.missing.append(f"{vehicle_id}: fixed_route_cost")
    if config.cost_per_km is None:
        resolved.missing.append(f"{vehicle_id}: cost_per_km")

    # The vehicle's live/base city is the dispatch anchor when it maps to a
    # known hub: a Hyderabad vehicle starts at Hyderabad, visits the closest
    # feasible Hyderabad-area work first through the hub-aware objective, and
    # returns to Hyderabad. This also prevents a stale manually seeded config
    # from silently routing a Delhi vehicle out of another city.
    if location_hub is not None:
        resolved.start_hub = location_hub
        resolved.end_hub = location_hub
    else:
        resolved.start_hub = db.get(Hub, config.base_hub_id) if config.base_hub_id else None
        # No explicit destination means return to the hub the vehicle left.
        resolved.end_hub = db.get(Hub, config.end_hub_id) if config.end_hub_id else resolved.start_hub

    if require_hub and resolved.start_hub is None:
        resolved.missing.append(f"{vehicle_id}: base hub")

    return resolved


def resolve_driver_cost_per_hour(db: Session, driver_id: str | None) -> float | None:
    if not driver_id:
        return None
    config = db.get(DriverDispatchConfig, driver_id)
    return config.cost_per_hour if config else None


def ensure_driver_cost_configuration(db: Session) -> int:
    """Persist baseline hourly rates for drivers without dispatch-cost data.

    Driver master records are imported separately from app-owned dispatch
    settings. Filling only missing rows lets fleet planning price every selected
    driver while preserving every existing business-approved rate.
    """
    drivers = db.execute(select(Driver).order_by(Driver.driver_id)).scalars().all()
    changed = 0
    for index, driver in enumerate(drivers):
        config = db.get(DriverDispatchConfig, driver.driver_id)
        if config is None:
            config = DriverDispatchConfig(driver_id=driver.driver_id)
            db.add(config)
        if config.cost_per_hour is None:
            config.cost_per_hour = DEFAULT_DRIVER_HOURLY_RATES[index % len(DEFAULT_DRIVER_HOURLY_RATES)]
            changed += 1
    if changed:
        db.commit()
    return changed
