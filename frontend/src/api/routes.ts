import { apiClient } from "./client";
import type { CreateRoutePayload, Route } from "@/types/route";

export async function fetchRoutes(): Promise<Route[]> {
  const { data } = await apiClient.get<Route[]>("/routes");
  return data;
}

export async function createRoute(payload: CreateRoutePayload): Promise<Route> {
  const { data } = await apiClient.post<Route>("/routes", payload);
  return data;
}
