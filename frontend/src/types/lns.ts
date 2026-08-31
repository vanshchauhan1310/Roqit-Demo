/** LNS optimization run with before/after plan snapshots (impact panel). */

export interface LnsSnapshotStop {
  stop_id: string;
  trip_id: string | null;
  sequence: number;
  stop_type: string;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface LnsSnapshotRoute {
  name: string | null;
  vehicle_id: string | null;
  stops: LnsSnapshotStop[];
}

/** {route_id: snapshot} */
export type LnsPlanSnapshot = Record<string, LnsSnapshotRoute>;

export interface LnsRun {
  run_id: string;
  run_type: "TRIGGERED_LNS" | "PERIODIC_LNS";
  status: "completed" | "rolled_back" | "failed";
  old_cost: number | null;
  new_cost: number | null;
  improvement: number | null;
  improvement_pct: number | null;
  routes_affected: number;
  trips_reinserted: number | null;
  execution_time_ms: number;
  destroy_strategy: string | null;
  repair_strategy: string | null;
  created_at: string | null;
  routes_before: LnsPlanSnapshot | null;
  routes_after: LnsPlanSnapshot | null;
}

/** A trip that LNS moved between routes (for replay animation). */
export interface MovedTrip {
  tripId: string;
  from: [number, number];
  to: [number, number];
}