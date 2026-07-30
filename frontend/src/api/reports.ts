import { apiClient } from "./client";
import type { TripKpiSummary } from "@/types/report";

export async function fetchTripKpiSummary(): Promise<TripKpiSummary> {
  const { data } = await apiClient.get<TripKpiSummary>("/reports/trips/kpi-summary");
  return data;
}
