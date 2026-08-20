export interface OptimizeStopInput {
  key: string;
  latitude: number;
  longitude: number;
  trip_id: string;
  stop_type: "pickup" | "delivery";
  load_weight_kg: number | null;
}

export interface OptimizeRouteResult {
  order: string[];
  total_duration_seconds: number;
  total_distance_meters: number;
  solver_used: "exact" | "hybrid";
}
