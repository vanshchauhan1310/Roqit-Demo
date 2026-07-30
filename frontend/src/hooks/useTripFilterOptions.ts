import { useQuery } from "@tanstack/react-query";
import { fetchTripFilterOptions } from "@/api/trips";

export function useTripFilterOptions() {
  return useQuery({
    queryKey: ["trip-filter-options"],
    queryFn: fetchTripFilterOptions,
    staleTime: 5 * 60 * 1000,
  });
}
