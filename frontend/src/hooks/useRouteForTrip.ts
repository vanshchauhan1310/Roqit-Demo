import { useQuery } from "@tanstack/react-query";
import { fetchRoutesForTrip } from "@/api/routes";

export function useRouteForTrip(tripId: string) {
  return useQuery({
    queryKey: ["routes", "for-trip", tripId],
    queryFn: () => fetchRoutesForTrip(tripId),
    select: (routes) => routes[0] ?? null,
  });
}
