import { useQuery } from "@tanstack/react-query";
import { fetchVehicleIntelligence } from "@/api/trips";

export function useVehicleIntelligence(tripId: string) {
  return useQuery({
    queryKey: ["vehicle-intelligence", tripId],
    queryFn: () => fetchVehicleIntelligence(tripId),
    retry: false,
  });
}
