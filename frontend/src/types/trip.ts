export interface Trip {
  trip_id: string;
  driver_id: string | null;
  driver_name: string | null;
  vehicle_id: string | null;
  vehicle_type: string | null;
  origin: string | null;
  destination: string | null;
  status: string | null;
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
  profit_margin: number | null;
  stop_count: number;
  load_weight_kg: number | null;
  load_value: number | null;
}

export interface TripFilterOptions {
  statuses: string[];
  drivers: string[];
}

export interface TripFilters {
  search?: string;
  status?: string;
  driver?: string;
  pickupDate?: string; // YYYY-MM-DD
  unassigned?: boolean;
}

export interface CreateTripPayload {
  driver_id?: string | null;
  driver_name?: string | null;
  vehicle_id?: string | null;
  vehicle_type?: string | null;
  origin: string;
  destination: string;
  gps_start_lat?: number | null;
  gps_start_lon?: number | null;
  gps_end_lat?: number | null;
  gps_end_lon?: number | null;
  pickup_time?: string | null;
  planned_delivery_time?: string | null;
  planned_distance_km?: number | null;
  load_weight_kg?: number | null;
  load_value?: number | null;
  weather_condition?: string | null;
  road_type?: string | null;
  traffic_density?: string | null;
  fuel_price_per_l?: number | null;
}
