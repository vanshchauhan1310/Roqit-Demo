export interface OptimizeStopInput {
  key: string;
  latitude: number;
  longitude: number;
  trip_id: string;
  stop_type: "pickup" | "delivery";
  load_weight_kg: number | null;
  pickup_earliest: number | null;
  pickup_latest: number | null;
  delivery_earliest: number | null;
  delivery_latest: number | null;
  service_time_sec: number;
}

export interface OptimizeVehicleInput {
  vehicle_id: string;
  capacity_kg: number;
  start_location: number; // index into stops array for depot location
  avg_kmpl_rated: number;
  fuel_price_per_l: number;
}

export interface DepotInput {
  key: string;
  latitude: number;
  longitude: number;
  address?: string;
}

export interface CostWeightsInput {
  alpha: number;   // duration weight
  delta: number;   // distance weight
  beta: number;    // fuel weight
  gamma: number;   // load (ton-km) weight
  lateness_weight: number;
}

export interface OptimizeRouteRequest {
  stops: OptimizeStopInput[];
  vehicles?: OptimizeVehicleInput[]; // multi-vehicle support
  vehicle_capacity_kg: number | null; // legacy single vehicle support
  auto_generate_windows: boolean;
  start_time: number;
  vehicle_speed_kph: number;
  cost_weights?: CostWeightsInput;
  solver_time_limit_seconds: number;
  depot?: DepotInput; // explicit depot; if omitted, uses first stop as fallback
}

export interface VehicleRouteOutput {
  vehicle_id: string;
  stops: string[]; // stop keys in optimized visiting order
}

export interface OptimizeRouteResponse {
  routes?: VehicleRouteOutput[]; // multi-vehicle response
  order?: string[]; // legacy single vehicle response
  total_duration_seconds: number;
  total_distance_meters: number;
  total_lateness_seconds: number;
  total_fuel_cost_rupees: number;
  total_load_ton_km: number;
  solver_used: "or_tools" | "fallback" | "exact" | "hybrid";
  feasible: boolean;
}