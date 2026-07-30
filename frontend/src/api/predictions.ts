import { apiClient } from "./client";
import type { DelayPrediction } from "@/types/delayPrediction";

export async function predictDelayForTrip(tripId: string): Promise<DelayPrediction> {
  const { data } = await apiClient.post<DelayPrediction>(`/predictions/delay/trips/${tripId}`);
  return data;
}
