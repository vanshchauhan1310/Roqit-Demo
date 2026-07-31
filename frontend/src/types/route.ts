export type StopType = "pickup" | "waypoint" | "delivery";

export interface RouteStop {
  stop_id: string;
  sequence: number;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  eta: string | null;
  status: string;
  stop_type: StopType;
  window_start: string | null;
  window_end: string | null;
  weather_condition: string | null;
  weather_updated_at: string | null;
}

export interface Route {
  route_id: string;
  trip_id: string | null;
  name: string | null;
  status: string;
  created_at: string;
  stops: RouteStop[];
}

export interface RouteStopInput {
  sequence?: number;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  eta?: string | null;
  stop_type?: StopType;
  window_start?: string | null;
  window_end?: string | null;
}

export interface CreateRoutePayload {
  trip_id?: string | null;
  name?: string | null;
  stops: RouteStopInput[];
}

export type AddRouteStopPayload = RouteStopInput;
