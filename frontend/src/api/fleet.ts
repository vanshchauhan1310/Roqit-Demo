import { apiClient } from "./client";

export interface Vehicle {
  vehicle_id: string;
  vehicle_type: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  fuel_type: string | null;
  load_capacity_kg: number | null;
  avg_kmpl_rated: number | null;
  status: string | null;
  vehicle_age_years: number | null;
}

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

export async function fetchVehicles(limit = 500): Promise<Vehicle[]> {
  const { data } = await apiClient.get<Vehicle[]>("/vehicles", { params: { limit } });
  return data;
}

export async function fetchDrivers(limit = 500): Promise<Driver[]> {
  const { data } = await apiClient.get<Driver[]>("/drivers", { params: { limit } });
  return data;
}