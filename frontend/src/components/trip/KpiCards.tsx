import { useTripKpiSummary } from "@/hooks/useTripKpiSummary";
import type { TripKpiSummary } from "@/types/report";

interface KpiCardDef {
  label: string;
  value: string;
  valueTone?: "danger";
}

function buildKpiCards(kpi: TripKpiSummary): KpiCardDef[] {
  return [
    { label: "Total Trips", value: String(kpi.total_trips) },
    {
      label: "On-Time %",
      value: kpi.on_time_rate != null ? `${Math.round(kpi.on_time_rate * 100)}%` : "—",
    },
    {
      label: "Avg Delay",
      value: kpi.avg_delay_minutes != null ? `${Math.round(kpi.avg_delay_minutes)} min` : "—",
    },
    {
      label: "Avg Profit Margin",
      value: kpi.avg_profit_margin != null ? `${kpi.avg_profit_margin.toFixed(1)}%` : "—",
    },
    { label: "Active Trips", value: String(kpi.active_trips) },
    {
      label: "Delayed Trips",
      value: String(kpi.delayed_trips),
      valueTone: kpi.delayed_trips > 0 ? "danger" : undefined,
    },
  ];
}

export function KpiCards() {
  const { data, isLoading, isError } = useTripKpiSummary();

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 h-[76px] animate-pulse" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return <p className="text-sm text-red-600">Failed to load trip KPIs.</p>;
  }

  const cards = buildKpiCards(data);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
      {cards.map((kpi) => (
        <div key={kpi.label} className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-2">
            {kpi.label}
          </div>
          <span className={`text-2xl font-semibold ${kpi.valueTone === "danger" ? "text-red-600" : "text-gray-900"}`}>
            {kpi.value}
          </span>
        </div>
      ))}
    </div>
  );
}
