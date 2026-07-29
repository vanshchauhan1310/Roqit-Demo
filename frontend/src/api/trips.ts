import { apiClient } from "./client";
import type { CreateTripPayload, Trip } from "@/types/trip";

export async function fetchTrips(): Promise<Trip[]> {
  const { data } = await apiClient.get<Trip[]>("/trips");
  return data;
}

export async function fetchTrip(tripId: string): Promise<Trip> {
  const { data } = await apiClient.get<Trip>(`/trips/${tripId}`);
  return data;
}

export async function createTrip(payload: CreateTripPayload): Promise<Trip> {
  const { data } = await apiClient.post<Trip>("/trips", payload);
  return data;
}

export async function updateTripStatus(tripId: string, status: string): Promise<Trip> {
  const { data } = await apiClient.patch<Trip>(`/trips/${tripId}/status`, { status });
  return data;
}
