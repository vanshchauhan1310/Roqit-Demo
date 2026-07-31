import { apiClient } from "./client";
import type { CreateTripPayload, Trip, TripFilterOptions, TripFilters } from "@/types/trip";
import type { VehicleIntelligence } from "@/types/vehicleIntelligence";

export async function fetchTrips(skip = 0, limit = 100, filters: TripFilters = {}): Promise<Trip[]> {
  const { data } = await apiClient.get<Trip[]>("/trips", {
    params: {
      skip,
      limit,
      search: filters.search || undefined,
      status: filters.status || undefined,
      driver: filters.driver || undefined,
      pickup_date: filters.pickupDate || undefined,
    },
  });
  return data;
}

export async function fetchTripFilterOptions(): Promise<TripFilterOptions> {
  const { data } = await apiClient.get<TripFilterOptions>("/trips/filter-options");
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

export async function fetchVehicleIntelligence(tripId: string): Promise<VehicleIntelligence> {
  const { data } = await apiClient.get<VehicleIntelligence>(`/trips/${tripId}/vehicle-intelligence`);
  return data;
}
