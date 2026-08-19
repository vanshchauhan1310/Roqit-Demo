import { useQuery } from "@tanstack/react-query";
import { fetchUnassignedTrips } from "@/api/trips";
import type { Trip } from "@/types/trip";

export function useUnassignedTrips() {
  return useQuery<Trip[]>({
    queryKey: ["trips", "unassigned"],
    queryFn: fetchUnassignedTrips,
  });
}