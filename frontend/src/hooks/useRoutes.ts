import { useQuery } from "@tanstack/react-query";
import { fetchRoutes } from "@/api/routes";

export function useRoutes(tripId?: string) {
  return useQuery({
    queryKey: ["routes", tripId ?? null],
    queryFn: () => fetchRoutes(tripId),
  });
}
