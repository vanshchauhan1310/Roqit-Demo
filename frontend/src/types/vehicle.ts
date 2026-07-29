export interface Vehicle {
  vehicle_id: string;
  license_plate: string;
  make: string | null;
  model: string | null;
  year: number | null;
  status: string;
  created_at: string;
}
