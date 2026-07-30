import { apiClient } from "./client";
import type { GeocodeResult } from "@/types/geocode";

export async function geocodeAddress(address: string): Promise<GeocodeResult> {
  const { data } = await apiClient.post<GeocodeResult>("/geocode", { address });
  return data;
}
