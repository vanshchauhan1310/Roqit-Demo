export interface DriverRosterItem {
  driver_id: string;
  driver_name: string | null;
  phone: string | null;
  license_type: string | null;
  license_expiry: string | null;
  experience_years: number | null;
  base_location: string | null;
  rating: number | null;
  status: string | null;
  is_on_trip: boolean;
  license_expiring_soon: boolean | null;
  // Assignment-aware fields
  assignment_status: "available" | "assigned" | "unavailable";
  current_route_id: string | null;
  current_route_name: string | null;
  current_route_pickup_time: string | null;
  current_route_planned_delivery_time: string | null;
}

export interface VehicleRosterItem {
  vehicle_id: string;
  vehicle_type: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  fuel_type: string | null;
  load_capacity_kg: number | null;
  avg_kmpl_rated: number | null;
  base_location: string | null;
  hub_name: string | null;
  status: string | null;
  is_on_trip: boolean;
  service_due_soon: boolean | null;
  // Assignment-aware fields
  assignment_status: "available" | "assigned" | "unavailable";
  current_route_id: string | null;
  current_route_name: string | null;
  current_route_pickup_time: string | null;
  current_route_planned_delivery_time: string | null;
}
