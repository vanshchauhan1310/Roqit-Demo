import { useQuery } from "@tanstack/react-query";
import { fetchTripLiveStatus } from "@/api/realtime";

export function useRealtimeLive(tripId: string | undefined) {
  return useQuery({
    queryKey: ["realtime-live", tripId],
    queryFn: () => fetchTripLiveStatus(tripId as string),
    enabled: Boolean(tripId),
  });
}
