export interface Driver {
  driver_id: string;
  driver_name: string;
  phone: number | null;
  license_type: string | null;
  experience_years: number | null;
  rating: number | null;
  base_location: string | null;
  status: string | null;
}
