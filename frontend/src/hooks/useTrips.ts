import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchTrips } from "@/api/trips";
import type { TripFilters } from "@/types/trip";

export const TRIPS_PAGE_SIZE = 100;

export function useTrips(page: number, filters: TripFilters = {}) {
  const skip = (page - 1) * TRIPS_PAGE_SIZE;

  return useQuery({
    queryKey: ["trips", page, filters],
    queryFn: () => fetchTrips(skip, TRIPS_PAGE_SIZE, filters),
    placeholderData: keepPreviousData,
  });
}
