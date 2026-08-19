import { Trip } from "@/types/trip";
import { useTripKpiDetail } from "@/hooks/useTripKpiDetail";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface ReportingKpiTabProps {
  trip: Trip;
}

function formatNumber(value: number | null, suffix = ""): string {
  return value != null ? `${value.toLocaleString()}${suffix}` : "—";
}

function formatPercent(value: number | null): string {
  return value != null ? `${(value * 100).toFixed(1)}%` : "—";
}

function formatDuration(minutes: number | null): string {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

const STATUS_COLORS: Record<string, string> = {
  delivered: "#059669",
  delayed: "#d97706",
  "in-transit": "#0284c7",
  scheduled: "#6b7280",
  planned: "#6b7280",
  cancelled: "#dc2626",
};

const DELAY_COLORS: Record<string, string> = {
  "On time": "#059669",
  "≤30m": "#0d9488",
  "31–60m": "#0284c7",
  "61–90m": "#d97706",
  ">90m": "#dc2626",
};

export function ReportingKpiTab({ trip }: ReportingKpiTabProps) {
  const { data, isLoading, isError } = useTripKpiDetail();

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading reporting & KPI…</p>;
  }

  if (isError || !data) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6 text-sm text-gray-500">
        Reporting data is unavailable right now.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <KpiStatCards kpi={data} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <StatusDistributionCard data={data.status_distribution} />
        <DelayBucketsCard data={data.delay_buckets} />
      </div>

      <TripSnapshot trip={trip} />
    </div>
  );
}

function KpiStatCards({ kpi }: { kpi: ReturnType<typeof useTripKpiDetail>["data"] }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
      <StatCard label="Total trips" value={formatNumber(kpi?.total_trips ?? 0)} />
      <StatCard
        label="On-time rate"
        value={formatPercent(kpi?.on_time_rate ?? null)}
        accent={kpi?.on_time_rate != null && kpi.on_time_rate >= 0.85 ? "text-emerald-600" : "text-amber-600"}
      />
      <StatCard label="Active trips" value={formatNumber(kpi?.active_trips ?? 0)} />
      <StatCard
        label="Delayed trips"
        value={formatNumber(kpi?.delayed_trips ?? 0)}
        accent={(kpi?.delayed_trips ?? 0) > 0 ? "text-amber-600" : "text-gray-900"}
      />
      <StatCard
        label="Avg delay (delayed)"
        value={formatDuration(kpi?.avg_delay_minutes ?? null)}
        accent={(kpi?.avg_delay_minutes ?? 0) > 60 ? "text-red-600" : "text-amber-600"}
      />
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">{label}</div>
      <div className={`text-xl font-semibold mt-1 ${accent ?? "text-gray-900"}`}>{value}</div>
    </div>
  );
}

function StatusDistributionCard({ data }: { data: { status: string; count: number }[] }) {
  const chartData = data
    .map((bucket) => ({
      name: bucket.status.charAt(0).toUpperCase() + bucket.status.slice(1),
      value: bucket.count,
    }))
    .filter((bucket) => bucket.value > 0);

  if (chartData.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <h3 className="text-sm font-semibold text-gray-900">Status distribution</h3>
        <p className="text-xs text-gray-400 mt-2">No trips recorded yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Status distribution</h3>
      <p className="text-xs text-gray-500 mt-0.5 mb-2">Fleet-wide trip mix</p>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={45}
              outerRadius={80}
              paddingAngle={2}
            >
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={STATUS_COLORS[entry.name.toLowerCase()] ?? "#94a3b8"} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => [value, "Trips"]} />
            <Legend iconType="circle" iconSize={8} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function DelayBucketsCard({ data }: { data: { label: string; count: number }[] }) {
  const chartData = data
    .map((bucket) => ({ name: bucket.label, count: bucket.count }))
    .filter((bucket) => bucket.count > 0);

  if (chartData.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <h3 className="text-sm font-semibold text-gray-900">Delay buckets</h3>
        <p className="text-xs text-gray-400 mt-2">No resolved trips to bucket yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Delay buckets</h3>
      <p className="text-xs text-gray-500 mt-0.5 mb-2">Resolved trips grouped by delay duration</p>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={{ stroke: "#e2e8f0" }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ fill: "#f8fafc" }} formatter={(value) => [value, "Trips"]} />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={DELAY_COLORS[entry.name] ?? "#94a3b8"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function TripSnapshot({ trip }: { trip: Trip }) {
  const onTime = trip.delay_minutes == null || trip.delay_minutes <= 0;
  const distanceKm = trip.actual_distance_km ?? trip.planned_distance_km;
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">This trip's snapshot</h3>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
        <SnapshotTile label="Status" value={trip.status ?? "—"} />
        <SnapshotTile
          label="Delay"
          value={formatDuration(trip.delay_minutes)}
          accent={trip.delay_minutes != null && trip.delay_minutes > 0 ? "text-amber-600" : "text-emerald-600"}
          sub={trip.delay_minutes != null ? (onTime ? "On time" : "Late") : undefined}
        />
        <SnapshotTile
          label="Profit margin"
          value={trip.profit_margin != null ? `${trip.profit_margin.toFixed(1)}%` : "—"}
          accent={trip.profit_margin != null && trip.profit_margin < 0 ? "text-red-600" : "text-gray-900"}
        />
        <SnapshotTile
          label="Distance"
          value={distanceKm != null ? `${distanceKm.toLocaleString()} km` : "—"}
        />
      </div>
    </div>
  );
}

function SnapshotTile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3">
      <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">{label}</div>
      <div className={`text-base font-semibold mt-0.5 ${accent ?? "text-gray-900"}`}>{value}</div>
      {sub && <div className="text-[10px] text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}