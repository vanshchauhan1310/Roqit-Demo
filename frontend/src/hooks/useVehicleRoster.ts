import { useQuery } from "@tanstack/react-query";
import { fetchVehicleRoster } from "@/api/roster";

export function useVehicleRoster() {
  return useQuery({
    queryKey: ["vehicle-roster"],
    queryFn: fetchVehicleRoster,
  });
}
