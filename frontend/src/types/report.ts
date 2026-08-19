export interface TripKpiSummary {
  total_trips: number;
  on_time_rate: number | null;
  avg_delay_minutes: number | null;
  avg_profit_margin: number | null;
  active_trips: number;
  delayed_trips: number;
}

export interface StatusBucket {
  status: string;
  count: number;
}

export interface DelayBucket {
  label: string;
  count: number;
}

export interface TripKpiDetail extends TripKpiSummary {
  status_distribution: StatusBucket[];
  delay_buckets: DelayBucket[];
}
