import { useQuery } from "@tanstack/react-query";
import { predictDelayForTrip, predictExpectedDelayForTrip } from "@/api/predictions";
import { DelayBadge } from "./DelayBadge";

interface TripDelayBadgeProps {
  tripId: string;
}

/**
 * Fetches the ML delay prediction + expected ETA delta for a trip and renders
 * the shared DelayBadge. Self-contained so any list row can drop it in.
 */
export function TripDelayBadge({ tripId }: TripDelayBadgeProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["delay", tripId],
    queryFn: async () => {
      const [prob, expected] = await Promise.all([
        predictDelayForTrip(tripId).catch(() => null),
        predictExpectedDelayForTrip(tripId).catch(() => null),
      ]);
      return {
        prediction: prob,
        expectedMinutes: expected?.predicted_delay_minutes ?? null,
      };
    },
    enabled: !!tripId,
    refetchInterval: 300_000,
    staleTime: 120_000,
  });

  if (isError) return null;

  return (
    <DelayBadge
      prediction={data?.prediction ?? undefined}
      loading={isLoading}
      expectedMinutes={data?.expectedMinutes ?? undefined}
    />
  );
}