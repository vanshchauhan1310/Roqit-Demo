export type TripStatus = "scheduled" | "in_progress" | "completed" | "cancelled";

export interface Trip {
  trip_id: string;
  vehicle_id: string | null;
  driver_id: string | null;
  origin: string | null;
  destination: string | null;
  status: TripStatus;
  scheduled_start: string | null;
  scheduled_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTripPayload {
  vehicle_id?: string | null;
  driver_id?: string | null;
  origin?: string | null;
  destination?: string | null;
  scheduled_start?: string | null;
  scheduled_end?: string | null;
}
