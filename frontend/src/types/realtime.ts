export interface RealtimeLive {
  trip_id: string;
  status: string | null;
  vehicle_id: string | null;
  vehicle_status: string | null;
  current_lat: number | null;
  current_lon: number | null;
  current_speed_kmph: number | null;
  alert_flag: string | null;
  last_updated: string | null;
  breadcrumb_count: number;
  latest_speed_kmph: number | null;
  latest_heading_deg: number | null;
  latest_timestamp: string | null;
}
