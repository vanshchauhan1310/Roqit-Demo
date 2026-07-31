import { apiClient } from "./client";
import type { DelayPrediction, ExpectedDelay } from "@/types/delayPrediction";

export async function predictDelayForTrip(tripId: string): Promise<DelayPrediction> {
  const { data } = await apiClient.post<DelayPrediction>(`/predictions/delay/trips/${tripId}`);
  return data;
}

export async function predictExpectedDelayForTrip(tripId: string): Promise<ExpectedDelay> {
  const { data } = await apiClient.post<ExpectedDelay>(`/predictions/expected-delay/trips/${tripId}`);
  return data;
}
