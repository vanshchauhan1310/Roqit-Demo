import type { OptimizeStopInput } from "./optimize";

/** Typed business outcomes. A predictable rejection is one of these with HTTP 200 —
 *  never a 500. See backend/app/schemas/optimize.py::FleetOptimizeStatus. */
export type FleetOptimizeStatus =
  | "SUCCESS"
  | "PARTIAL"
  | "NO_FEASIBLE_SOLUTION"
  | "NO_FEASIBLE_ASSIGNMENT"
  | "MISSING_REQUIRED_DATA"
  | "MISSING_COST_DATA"
  | "MISSING_HUB_DATA"
  | "DRIVER_UNAVAILABLE"
  | "VEHICLE_UNAVAILABLE"
  | "CAPACITY_VIOLATION"
  | "PICKUP_DROP_VIOLATION"
  | "ROUTE_DURATION_VIOLATION";

/** The dispatcher supplies only WHICH vehicle and driver are available. Capacity,
 *  mileage, hub and every cost rate are resolved server-side — the client can't
 *  supply rates that would skew the assignment. */
export interface FleetVehicleSelection {
  vehicle_id: string;
  driver_id: string | null;
}

export interface FleetRouteMetrics {
  distance_meters: number;
  duration_seconds: number;
  fuel_liters: number;
  fuel_cost: number;
  driver_cost: number;
  operating_cost: number;
  fixed_cost: number;
  peak_load_kg: number;
  total_cost: number;
  /** False when total_cost is a duration proxy rather than real currency.
   *  Never render it with a ₹ symbol in that case. */
  cost_is_monetary: boolean;
}

export interface FleetVehicleRoute {
  vehicle_id: string;
  driver_id: string | null;
  order: string[]; // stop keys in visiting order
  trip_ids: string[];
  metrics: FleetRouteMetrics;
}

// Diagnostic types for unassigned trips
export interface VehicleInsertionDiagnostic {
  vehicle_id: string;
  vehicle_capacity_kg: number | null;
  current_peak_load_kg: number;
  static_remaining_capacity_kg: number | null;
  trip_weight_kg: number;
  total_pickup_positions_tested: number;
  total_delivery_positions_tested: number;
  capacity_failures: number;
  precedence_failures: number;
  feasible_insertions: number;
  best_peak_load_kg: number | null;
  best_incremental_cost: number | null;
  best_pickup_position: number | null;
  best_delivery_position: number | null;
}

export interface TripAssignmentDiagnostic {
  trip_id: string;
  trip_weight_kg: number;
  status: "ASSIGNED" | "UNASSIGNED" | "EXCEEDS_ALL_VEHICLES";
  primary_failure_reason: string | null;
  capacity_failures: number;
  precedence_failures: number;
  total_positions_tested: number;
  minimum_required_capacity_kg: number | null;
  vehicle_diagnostics: VehicleInsertionDiagnostic[];
}

export interface OptimizeFleetResult {
  status: FleetOptimizeStatus;
  routes: FleetVehicleRoute[];
  unassigned_trip_ids: string[];
  totals: FleetRouteMetrics;
  vehicles_used: number;
  explanation: string[];
  warnings: string[];
  unassigned_diagnostics: TripAssignmentDiagnostic[];
}

export interface OptimizeFleetPayload {
  stops: OptimizeStopInput[];
  vehicles: FleetVehicleSelection[];
  require_monetary_cost?: boolean;
  require_hub_routing?: boolean;
  max_route_duration_seconds?: number;
}
