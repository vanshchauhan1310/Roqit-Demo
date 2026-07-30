import { useQuery } from "@tanstack/react-query";
import { fetchDriverRoster } from "@/api/roster";

export function useDriverRoster() {
  return useQuery({
    queryKey: ["driver-roster"],
    queryFn: fetchDriverRoster,
  });
}
