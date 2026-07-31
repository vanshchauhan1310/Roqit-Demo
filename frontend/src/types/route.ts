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
  weather_description: string | null;
  temperature_c: number | null;
  wind_speed_ms: number | null;
}

export interface WeatherEtaEstimate {
  route_id: string;
  origin_latitude: number;
  origin_longitude: number;
  weather_condition: string;
  weather_description: string;
  temperature_c: number | null;
  wind_speed_ms: number | null;
  distance_km: number;
  base_duration_minutes: number;
  weather_delay_multiplier: number;
  adjusted_duration_minutes: number;
}

export interface Route {
  route_id: string;
  trip_id: string | null;
  name: string | null;
  status: string;
  created_at: string;
  stops: RouteStop[];
  weather_eta: WeatherEtaEstimate | null;
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
