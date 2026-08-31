import { useQuery } from "@tanstack/react-query";
import { fetchVehicles, fetchDrivers, type Vehicle, type Driver } from "@/api/fleet";

export function useFleet(pollMs = 15000) {
  const vehiclesQ = useQuery<Vehicle[], Error>({
    queryKey: ["fleet-vehicles"],
    queryFn: () => fetchVehicles(),
    refetchInterval: pollMs,
  });
  const driversQ = useQuery<Driver[], Error>({
    queryKey: ["fleet-drivers"],
    queryFn: () => fetchDrivers(),
    refetchInterval: pollMs,
  });
  return {
    vehicles: vehiclesQ.data ?? [],
    drivers: driversQ.data ?? [],
    loading: vehiclesQ.isLoading || driversQ.isLoading,
  };
}