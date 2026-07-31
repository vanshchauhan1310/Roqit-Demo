import { useQuery } from "@tanstack/react-query";
import { fetchTripBreadcrumbs } from "@/api/realtime";

export function useTripBreadcrumbs(tripId: string | undefined) {
  return useQuery({
    queryKey: ["trip-breadcrumbs", tripId],
    queryFn: () => fetchTripBreadcrumbs(tripId as string),
    enabled: Boolean(tripId),
  });
}
