export interface OptimizeStopInput {
  key: string;
  latitude: number;
  longitude: number;
  trip_id: string;
  stop_type: "pickup" | "delivery";
  load_weight_kg: number | null;
  assigned_weight_kg?: number | null;
  parent_trip_id?: string;
  original_load_weight_kg?: number | null;
  allowed_vehicle_ids?: string[];
  allow_split_loads?: boolean;
}

export interface OptimizeRouteResult {
  order: string[];
  total_duration_seconds: number;
  total_distance_meters: number;
  solver_used: "exact" | "hybrid";
}
