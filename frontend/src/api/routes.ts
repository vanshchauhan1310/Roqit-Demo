import { apiClient } from "./client";
import type { AddRouteStopPayload, CreateFleetPlanPayload, CreateRoutePayload, Route, RouteStop } from "@/types/route";
import type { OptimizeRouteResult, OptimizeStopInput } from "@/types/optimize";
import type { OptimizeFleetPayload, OptimizeFleetResult } from "@/types/fleet";
import type { RouteAssignPayload, RouteReorderPayload } from "@/types/route";

export async function fetchRoutes(tripId?: string): Promise<Route[]> {
  const { data } = await apiClient.get<Route[]>("/routes", { params: tripId ? { trip_id: tripId } : undefined });
  return data;
}

export async function fetchRoute(routeId: string): Promise<Route> {
  const { data } = await apiClient.get<Route>(`/routes/${routeId}`);
  return data;
}

export async function createRoute(payload: CreateRoutePayload): Promise<Route> {
  const { data } = await apiClient.post<Route>("/routes", payload);
  return data;
}

export async function createFleetPlanRoutes(payload: CreateFleetPlanPayload): Promise<Route[]> {
  const { data } = await apiClient.post<Route[]>("/routes/fleet-plan", payload);
  return data;
}

export async function addRouteStop(routeId: string, payload: AddRouteStopPayload): Promise<RouteStop> {
  const { data } = await apiClient.post<RouteStop>(`/routes/${routeId}/stops`, payload);
  return data;
}

export async function optimizeRouteOrder(
  stops: OptimizeStopInput[],
  vehicleCapacityKg: number | null,
  avgKmplRated: number | null = null,
  fuelPricePerL: number | null = null,
): Promise<OptimizeRouteResult> {
  const { data } = await apiClient.post<OptimizeRouteResult>("/routes/optimize", {
    stops,
    vehicle_capacity_kg: vehicleCapacityKg,
    avg_kmpl_rated: avgKmplRated,
    fuel_price_per_l: fuelPricePerL,
  });
  return data;
}

/** Multi-vehicle: the optimizer decides which vehicle serves which trip.
 *  Business outcomes arrive as `status` on a 200 — only transport/input failures throw. */
export async function optimizeFleet(payload: OptimizeFleetPayload): Promise<OptimizeFleetResult> {
  const { data } = await apiClient.post<OptimizeFleetResult>("/routes/optimize-fleet", payload);
  return data;
}

export async function assignRoute(payload: RouteAssignPayload): Promise<Route> {
  const { data } = await apiClient.post<Route>("/routes/assign", payload);
  return data;
}

export async function reorderRouteStops(routeId: string, payload: RouteReorderPayload): Promise<Route> {
  const { data } = await apiClient.patch<Route>(`/routes/${routeId}/stops/reorder`, payload);
  return data;
}

export async function assignRouteToTrip(routeId: string, tripId: string): Promise<Route> {
  const { data } = await apiClient.patch<Route>(`/routes/${routeId}/trip`, { trip_id: tripId });
  return data;
}
