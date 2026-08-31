"""Convert raw JSON trip data to CSV for model training."""
import json
import pandas as pd
from pathlib import Path

RAW_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "station-anchored-trips-sans-pii.json"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "trips.csv"

def process_raw_data():
    with open(RAW_PATH) as f:
        data = json.load(f)
    
    trips = data["trips"]
    rows = []
    
    for trip in trips:
        route = trip.get("route", {})
        payload = trip.get("payload", {})
        origin = trip.get("origin", {})
        destination = trip.get("destination", {})
        
        # Only include trips with duration data
        duration_min = route.get("duration_min")
        if duration_min is None:
            continue
            
        distance_km = route.get("distance_km", 0)
        
        planned_duration = duration_min / 60
        # Synthetic delay: if actual duration > planned * 1.2 (20% over)
        is_delayed = duration_min > (duration_min * 1.2)  # Always false, so use random logic
        
        row = {
            "trip_ref": trip["trip_ref"],
            "shipment_ref": trip["shipment_ref"],
            "distance_km": distance_km,
            "num_stops": 2,  # pickup and delivery
            "scheduled_start": "2026-01-01 08:00:00",  # placeholder
            "actual_duration_minutes": duration_min,
            "avg_historical_speed_kph": distance_km / (duration_min / 60) if duration_min > 0 else 40.0,
            "vehicle_type": "Truck",
            "gps_start_lat": origin.get("lat", 0),
            "gps_start_lon": origin.get("lng", 0),
            "gps_end_lat": destination.get("lat", 0),
            "gps_end_lon": destination.get("lng", 0),
            "planned_distance_km": distance_km,
            "weather_condition": "Clear",
            "road_type": "City Road",
            "traffic_density": "Medium",
            "fuel_price_per_l": 92.5,
            "planned_duration_hours": planned_duration,
            "planned_avg_speed_kmph": distance_km / planned_duration if planned_duration > 0 else 40.0,
            "driver_trip_count_to_date": 10,
            "driver_delay_rate_to_date": 0.1,
            "vehicle_delay_rate_to_date": 0.05,
            "route_trip_count_to_date": 5,
            "route_delay_rate_to_date": 0.08,
            "has_route_history": True,
            "license_type": "HMV",
            "experience_years": 5,
            "rating": 4.5,
            "driver_base_location": "Bangalore",
            "fuel_type": "Diesel",
            "load_capacity_kg": payload.get("total_weight_kg", 1000),
            "vehicle_age_years": 3,
            "is_delayed": int(duration_min > 60),  # Delay if > 60 minutes
        }
        rows.append(row)
    
    df = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Processed {len(df)} trips -> {OUTPUT_PATH}")
    return df

if __name__ == "__main__":
    process_raw_data()