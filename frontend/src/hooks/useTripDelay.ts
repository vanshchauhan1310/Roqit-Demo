import { useQuery } from "@tanstack/react-query";
import { predictDelayForTrip, predictExpectedDelayForTrip } from "@/api/predictions";

export function useTripDelayPrediction(tripId: string | null) {
  return useQuery({
    queryKey: ["delay-prediction", tripId],
    queryFn: () => predictDelayForTrip(tripId!),
    enabled: !!tripId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useTripExpectedDelay(tripId: string | null) {
  return useQuery({
    queryKey: ["expected-delay", tripId],
    queryFn: () => predictExpectedDelayForTrip(tripId!),
    enabled: !!tripId,
    staleTime: 5 * 60 * 1000,
  });
}