import { apiClient } from "./client";
import type { DriverRosterItem, VehicleRosterItem } from "@/types/roster";

export async function fetchDriverRoster(): Promise<DriverRosterItem[]> {
  const { data } = await apiClient.get<DriverRosterItem[]>("/roster/drivers");
  return data;
}

export async function fetchVehicleRoster(): Promise<VehicleRosterItem[]> {
  const { data } = await apiClient.get<VehicleRosterItem[]>("/roster/vehicles");
  return data;
}
