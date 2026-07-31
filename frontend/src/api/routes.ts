import { apiClient } from "./client";
import type { AddRouteStopPayload, CreateRoutePayload, Route, RouteStop } from "@/types/route";
import type { OptimizeRouteResult, OptimizeStopInput } from "@/types/optimize";

export async function fetchRoutes(): Promise<Route[]> {
  const { data } = await apiClient.get<Route[]>("/routes");
  return data;
}

export async function fetchRoutesForTrip(tripId: string): Promise<Route[]> {
  const { data } = await apiClient.get<Route[]>("/routes", { params: { trip_id: tripId } });
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

export async function optimizeRouteOrder(stops: OptimizeStopInput[]): Promise<OptimizeRouteResult> {
  const { data } = await apiClient.post<OptimizeRouteResult>("/routes/optimize", { stops });
  return data;
}

export async function assignRouteToTrip(routeId: string, tripId: string): Promise<Route> {
  const { data } = await apiClient.patch<Route>(`/routes/${routeId}/trip`, { trip_id: tripId });
  return data;
}
