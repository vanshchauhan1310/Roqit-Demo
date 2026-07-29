import { useQuery } from "@tanstack/react-query";
import { fetchTrip } from "@/api/trips";

export function useTripDetail(tripId: string | undefined) {
  return useQuery({
    queryKey: ["trip", tripId],
    queryFn: () => fetchTrip(tripId as string),
    enabled: Boolean(tripId),
  });
}
