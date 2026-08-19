import { useQuery } from "@tanstack/react-query";
import { fetchRoute } from "@/api/routes";

export function useRouteDetail(routeId: string | undefined) {
  return useQuery({
    queryKey: ["route", routeId],
    queryFn: () => fetchRoute(routeId as string),
    enabled: Boolean(routeId),
  });
}