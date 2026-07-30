import { useQuery } from "@tanstack/react-query";
import { fetchRoutes } from "@/api/routes";

export function useRoutes() {
  return useQuery({
    queryKey: ["routes"],
    queryFn: fetchRoutes,
  });
}
