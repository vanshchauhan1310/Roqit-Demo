export type TripStatus = "Delayed" | "Delivered" | "In-Transit" | "Cancelled";

export interface Trip {
  trip_id: string;
  vehicle_id: string | null;
  driver_id: string | null;
  driver_name: string | null;
  vehicle_type: string | null;
  origin: string | null;
  destination: string | null;
  status: TripStatus | null;
  is_delayed: boolean | null;

  gps_start_lat: number | null;
  gps_start_lon: number | null;
  gps_end_lat: number | null;
  gps_end_lon: number | null;
  planned_distance_km: number | null;
  actual_distance_km: number | null;
  weather_condition: string | null;
  road_type: string | null;
  traffic_density: string | null;
  fuel_price_per_l: number | null;

  pickup_time: string | null;
  planned_delivery_time: string | null;
  actual_delivery_time: string | null;
  delay_minutes: number | null;
}

export interface CreateTripPayload {
  trip_id: string;
  vehicle_id?: string | null;
  driver_id?: string | null;
  driver_name?: string | null;
  vehicle_type?: string | null;
  origin?: string | null;
  destination?: string | null;
  gps_start_lat?: number | null;
  gps_start_lon?: number | null;
  gps_end_lat?: number | null;
  gps_end_lon?: number | null;
  planned_distance_km?: number | null;
  weather_condition?: string | null;
  road_type?: string | null;
  traffic_density?: string | null;
  fuel_price_per_l?: number | null;
  pickup_time?: string | null;
  planned_delivery_time?: string | null;
}
