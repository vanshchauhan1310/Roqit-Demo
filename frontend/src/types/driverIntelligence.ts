export interface DriverTripRead {
  trip_id: string;
  origin: string | null;
  destination: string | null;
  status: string | null;
  pickup_time: string | null;
  actual_delivery_time: string | null;
  delay_minutes: number | null;
  profit_margin: number | null;
}

export interface DriverHoursRead {
  date: string | null;
  trips_count: number | null;
  hours_driven: number | null;
  rest_hours: number | null;
  hos_compliant: boolean | null;
}

export interface DriverBehavior {
  speeding_incidents: number;
  harsh_braking_count: number;
  harsh_accel_count: number;
  violation_count: number;
}

export interface DriverIntelligence {
  driver_id: string;
  driver_name: string | null;
  phone: string | null;
  license_type: string | null;
  license_expiry: string | null;
  experience_years: number | null;
  base_location: string | null;
  rating: number | null;
  status: string | null;
  is_on_trip: boolean;
  license_expiring_soon: boolean | null;
  total_trips: number;
  on_time_rate: number | null;
  avg_delay_minutes: number | null;
  avg_profit_margin: number | null;
  delayed_trips: number;
  behavior: DriverBehavior;
  hos_history: DriverHoursRead[];
  recent_trips: DriverTripRead[];
}
