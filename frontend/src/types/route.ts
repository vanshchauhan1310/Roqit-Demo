export interface RouteStop {
  stop_id: string;
  sequence: number;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  eta: string | null;
  status: string;
}

export interface Route {
  route_id: string;
  trip_id: string | null;
  name: string | null;
  status: string;
  created_at: string;
  stops: RouteStop[];
}

export interface CreateRoutePayload {
  trip_id?: string | null;
  name?: string | null;
  stops: Omit<RouteStop, "stop_id" | "status">[];
}
