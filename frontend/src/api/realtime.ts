import { apiClient } from "./client";
import type { GpsBreadcrumb } from "@/types/gpsBreadcrumb";

export async function fetchTripBreadcrumbs(tripId: string): Promise<GpsBreadcrumb[]> {
  const { data } = await apiClient.get<GpsBreadcrumb[]>(`/realtime/trips/${tripId}/breadcrumbs`);
  return data;
}
