import { useQuery } from "@tanstack/react-query";
import { fetchTrips } from "@/api/trips";

export function useTrips() {
  return useQuery({
    queryKey: ["trips"],
    queryFn: fetchTrips,
  });
}
