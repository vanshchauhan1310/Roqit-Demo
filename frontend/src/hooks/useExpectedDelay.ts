import { useQuery } from "@tanstack/react-query";
import { predictExpectedDelayForTrip } from "@/api/predictions";

export function useExpectedDelay(tripId: string) {
  return useQuery({
    queryKey: ["expected-delay", tripId],
    queryFn: () => predictExpectedDelayForTrip(tripId),
    staleTime: Infinity,
    retry: false,
  });
}
