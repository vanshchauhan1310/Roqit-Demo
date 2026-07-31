import { apiClient } from "./client";
import type { DelayPrediction } from "@/types/delayPrediction";
import type { MlEtaEstimate } from "@/types/mlEta";

export async function predictDelayForTrip(tripId: string): Promise<DelayPrediction> {
  const { data } = await apiClient.post<DelayPrediction>(`/predictions/delay/trips/${tripId}`);
  return data;
}

export async function predictMlEtaForTrip(tripId: string): Promise<MlEtaEstimate> {
  const { data } = await apiClient.get<MlEtaEstimate>(`/trips/${tripId}/eta-prediction`);
  return data;
}
