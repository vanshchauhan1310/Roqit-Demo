import { apiClient } from "./client";
import type { GpsBreadcrumb } from "@/types/gpsBreadcrumb";
import type { RealtimeLive } from "@/types/realtime";

export async function fetchTripBreadcrumbs(tripId: string): Promise<GpsBreadcrumb[]> {
  const { data } = await apiClient.get<GpsBreadcrumb[]>(`/realtime/trips/${tripId}/breadcrumbs`);
  return data;
}

export async function fetchTripLiveStatus(tripId: string): Promise<RealtimeLive> {
  const { data } = await apiClient.get<RealtimeLive>(`/realtime/trips/${tripId}/live`);
  return data;
}
