export interface GpsBreadcrumb {
  id: number;
  trip_id: string;
  vehicle_id: string | null;
  timestamp: string;
  lat: number | null;
  lon: number | null;
  speed_kmph: number | null;
  heading_deg: number | null;
}
