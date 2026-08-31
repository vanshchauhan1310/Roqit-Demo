import { apiClient } from "./client";
import type { AddRouteStopPayload, CreateRoutePayload, Route, RouteStop } from "@/types/route";
import type { OptimizeStopInput, OptimizeVehicleInput, CostWeightsInput, OptimizeRouteResponse } from "@/types/optimize";
import type { LnsRun } from "@/types/lns";
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

export async function addRouteStop(routeId: string, payload: AddRouteStopPayload): Promise<RouteStop> {
  const { data } = await apiClient.post<RouteStop>(`/routes/${routeId}/stops`, payload);
  return data;
}

export async function optimizeRouteOrder(
  stops: OptimizeStopInput[],
  vehicles: OptimizeVehicleInput[] | null,
  vehicleCapacityKg: number | null,
  costWeights?: CostWeightsInput,
  startTime?: number,
  solverTimeLimitSeconds: number = 10,
  depot?: { key: string; latitude: number; longitude: number; address?: string },
): Promise<OptimizeRouteResponse> {
  const { data } = await apiClient.post<OptimizeRouteResponse>("/routes/optimize", {
    stops,
    vehicles,
    vehicle_capacity_kg: vehicleCapacityKg,
    auto_generate_windows: true,
    start_time: startTime ?? Math.floor(Date.now() / 1000),
    vehicle_speed_kph: 40,
    cost_weights: costWeights,
    solver_time_limit_seconds: solverTimeLimitSeconds,
    depot,
  });
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

export async function triggerLns(): Promise<{ message: string; job_id: string }> {
  const { data } = await apiClient.post<{ message: string; job_id: string }>("/routes/lns/trigger");
  return data;
}

export async function fetchLnsHistory(limit: number = 20): Promise<LnsRun[]> {
  const { data } = await apiClient.get<LnsRun[]>("/routes/lns/history", { params: { limit } });
  return data;
}

export async function fetchLnsRun(runId: string): Promise<LnsRun> {
  const { data } = await apiClient.get<LnsRun>(`/routes/lns/history/${runId}`);
  return data;
}