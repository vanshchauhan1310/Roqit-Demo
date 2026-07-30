export interface TripKpiSummary {
  total_trips: number;
  on_time_rate: number | null;
  avg_delay_minutes: number | null;
  avg_profit_margin: number | null;
  active_trips: number;
  delayed_trips: number;
}
