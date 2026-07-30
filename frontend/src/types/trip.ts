export interface Trip {
  trip_id: string;
  driver_id: string | null;
  driver_name: string | null;
  vehicle_id: string | null;
  vehicle_type: string | null;
  origin: string | null;
  destination: string | null;
  pickup_time: string | null;
  planned_delivery_time: string | null;
  actual_delivery_time: string | null;
  delay_minutes: number | null;
  status: string | null;
  profit_margin: number | null;
  stop_count: number;
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
}

export interface CreateTripPayload {
  driver_id: string;
  driver_name?: string | null;
  vehicle_id: string;
  vehicle_type?: string | null;
  origin: string;
  destination: string;
  gps_start_lat?: number | null;
  gps_start_lon?: number | null;
  gps_end_lat?: number | null;
  gps_end_lon?: number | null;
  pickup_time: string;
  planned_delivery_time?: string | null;
  planned_distance_km?: number | null;
  load_weight_kg?: number | null;
  load_value?: number | null;
}
