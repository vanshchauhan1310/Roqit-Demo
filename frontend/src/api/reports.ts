import { apiClient } from "./client";
import type { TripKpiDetail, TripKpiSummary } from "@/types/report";

export async function fetchTripKpiSummary(): Promise<TripKpiSummary> {
  const { data } = await apiClient.get<TripKpiSummary>("/reports/trips/kpi-summary");
  return data;
}

export async function fetchTripKpiDetail(): Promise<TripKpiDetail> {
  const { data } = await apiClient.get<TripKpiDetail>("/reports/trips/kpi-detail");
  return data;
}
