import { useQuery } from "@tanstack/react-query";
import { fetchDriverIntelligence } from "@/api/trips";

export function useDriverIntelligence(tripId: string | undefined) {
  return useQuery({
    queryKey: ["driver-intelligence", tripId],
    queryFn: () => fetchDriverIntelligence(tripId as string),
    enabled: Boolean(tripId),
    retry: false,
  });
}
