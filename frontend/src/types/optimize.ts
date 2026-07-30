export interface OptimizeStopInput {
  key: string;
  latitude: number;
  longitude: number;
}

export interface OptimizeRouteResult {
  order: string[];
  total_duration_seconds: number;
  total_distance_meters: number;
}
