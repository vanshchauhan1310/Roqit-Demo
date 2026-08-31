import { useQuery } from "@tanstack/react-query";
import { fetchTrips } from "@/api/trips";
import { fetchRoutes } from "@/api/routes";
import type { Trip } from "@/types/trip";
import type { Route } from "@/types/route";

/**
 * Live-polling hooks powering the Live Assignment page.
 * Incoming trips poll fast (new trips should appear within seconds);
 * trips/routes poll slower since assignment is asynchronous.
 */

export function useIncomingTrips(pollMs = 4000) {
  return useQuery<Trip[], Error>({
    queryKey: ["live-incoming-trips"],
    queryFn: () => fetchTrips(0, 200, { unassigned: true }),
    refetchInterval: pollMs,
  });
}

export function useAllTripsLive(pollMs = 8000) {
  return useQuery<Trip[], Error>({
    queryKey: ["live-all-trips"],
    queryFn: () => fetchTrips(0, 300),
    refetchInterval: pollMs,
  });
}

export function useRoutesLive(pollMs = 8000) {
  return useQuery<Route[], Error>({
    queryKey: ["live-routes"],
    queryFn: () => fetchRoutes(),
    refetchInterval: pollMs,
  });
}