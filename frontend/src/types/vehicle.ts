export interface Vehicle {
  vehicle_id: string;
  vehicle_type: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  fuel_type: string | null;
  load_capacity_kg: number | null;
  status: string | null;
  vehicle_age_years: number | null;
}
