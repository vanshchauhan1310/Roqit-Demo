"""Service-area enforcement: trips are only accepted inside Hyderabad.

Production rule — the optimization engine plans routes within the Hyderabad
metro area. Trips whose pickup or delivery GPS falls outside the service
boundary are rejected at ingestion (HTTP 422) rather than silently failing
feasibility later.
"""

# Hyderabad metropolitan bounding box (generous — covers the ORR and key
# outskirts: Shamshabad airport in the south, Ramoji Film City in the east,
# Patancheru/Bollaram industrial belt in the west).
HYDERABAD_BOUNDS = {
    "min_lat": 17.15,
    "max_lat": 17.80,
    "min_lon": 78.15,
    "max_lon": 78.85,
}

HYDERABAD_CENTER = (17.3850, 78.4867)  # (lat, lon) — map default view

# Friendly radius (km) shown in error messages.
SERVICE_AREA_NAME = "Hyderabad"


class TripOutsideServiceAreaError(ValueError):
    """Raised when a trip's GPS coordinates fall outside the service area."""

    def __init__(self, field: str, lat: float, lon: float):
        self.field = field
        self.lat = lat
        self.lon = lon
        super().__init__(
            f"{field} ({lat:.5f}, {lon:.5f}) is outside the {SERVICE_AREA_NAME} "
            f"service area. Trips must start and end within "
            f"[{HYDERABAD_BOUNDS['min_lat']}, {HYDERABAD_BOUNDS['min_lon']}] to "
            f"[{HYDERABAD_BOUNDS['max_lat']}, {HYDERABAD_BOUNDS['max_lon']}] "
            f"(lat, lon)."
        )


def is_within_hyderabad(lat: float, lon: float) -> bool:
    b = HYDERABAD_BOUNDS
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]


def validate_trip_within_service_area(
    gps_start_lat: float | None,
    gps_start_lon: float | None,
    gps_end_lat: float | None,
    gps_end_lon: float | None,
) -> None:
    """Raise TripOutsideServiceAreaError for any out-of-bounds trip endpoint.

    GPS pairs are validated only when both coordinates are present; a missing
    half of a pair is left to the existing coordinate-range validation.
    """
    if gps_start_lat is not None and gps_start_lon is not None:
        if not is_within_hyderabad(gps_start_lat, gps_start_lon):
            raise TripOutsideServiceAreaError("Trip pickup", gps_start_lat, gps_start_lon)

    if gps_end_lat is not None and gps_end_lon is not None:
        if not is_within_hyderabad(gps_end_lat, gps_end_lon):
            raise TripOutsideServiceAreaError("Trip delivery", gps_end_lat, gps_end_lon)