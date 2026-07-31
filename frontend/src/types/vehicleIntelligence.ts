export interface VehicleSummary {
  vehicle_id: string;
  vehicle_type: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  fuel_type: string | null;
  status: string | null;
  assigned: boolean;
  odometer_km: number | null;
}

export interface LoadCapacity {
  load_capacity_kg: number | null;
  load_weight_kg: number | null;
  utilization_pct: number | null;
}

export interface FuelEfficiencyComparison {
  this_trip_kmpl: number | null;
  rated_kmpl: number | null;
  fleet_avg_kmpl: number | null;
}

export interface MaintenanceEventItem {
  event_id: string;
  event_date: string | null;
  maintenance_type: string | null;
  description: string | null;
  downtime_hours: number | null;
  cost: number | null;
  odometer_at_service: number | null;
}

export interface MaintenanceStatus {
  last_service_date: string | null;
  next_service_due_km: number | null;
  pct_interval_consumed: number | null;
  history: MaintenanceEventItem[];
}

export interface CostSnapshot {
  fuel_cost: number | null;
  maintenance_cost: number | null;
  toll_cost: number | null;
  trip_tco: number | null;
  trip_cost_per_km: number | null;
  fleet_avg_cost_per_km: number | null;
}

export interface VehicleIntelligence {
  vehicle: VehicleSummary;
  load: LoadCapacity;
  fuel_efficiency: FuelEfficiencyComparison;
  maintenance: MaintenanceStatus;
  cost: CostSnapshot;
}
