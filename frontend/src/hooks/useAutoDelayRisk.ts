import { useQuery } from "@tanstack/react-query";
import { predictDelayForTrip } from "@/api/predictions";

/**
 * Auto-fetching variant of useDelayPrediction, for stat cards that should just
 * show a value on load rather than require a manual "Run Prediction" click.
 * Cached for the session so opening the tab repeatedly doesn't insert a fresh
 * delay_predictions row (and hit the ML service) every time.
 */
export function useAutoDelayRisk(tripId: string) {
  return useQuery({
    queryKey: ["auto-delay-risk", tripId],
    queryFn: () => predictDelayForTrip(tripId),
    staleTime: Infinity,
    retry: false,
  });
}
