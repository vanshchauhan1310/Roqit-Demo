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
    // limit must exceed the largest expected trip count - a low cap silently
    // clipped the "Trips today" KPI at a fixed-looking number.
    queryFn: () => fetchTrips(0, 1000),
    refetchInterval: pollMs,
  });
}

export function useRoutesLive(pollMs = 8000) {
  return useQuery<Route[], Error>({
    queryKey: ["live-routes"],
    queryFn: async () => {
      const allRoutes = await fetchRoutes();
      // Only count active routes (planned, active, in-transit)
      const ACTIVE_STATUSES = ["planned", "active", "in-transit"];
      return allRoutes.filter((r) => ACTIVE_STATUSES.includes((r.status || "").toLowerCase()));
    },
    refetchInterval: pollMs,
  });
}