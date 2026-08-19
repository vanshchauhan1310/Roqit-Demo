import { Trip } from "@/types/trip";
import { useDriverIntelligence } from "@/hooks/useDriverIntelligence";
import type { DriverHoursRead } from "@/types/driverIntelligence";

interface DriverIntelligenceTabProps {
  trip: Trip;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

function formatPercent(value: number | null): string {
  return value != null ? `${Math.round(value * 100)}%` : "—";
}

function formatDuration(minutes: number | null): string {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

export function DriverIntelligenceTab({ trip }: DriverIntelligenceTabProps) {
  const { data, isLoading, isError, error } = useDriverIntelligence(trip.trip_id);

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading driver intelligence…</p>;
  }

  if (isError || !data) {
    const detail =
      (error as { response?: { data?: { detail?: string } } } | undefined)?.response?.data?.detail ??
      "No driver intelligence available for this trip.";
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6 text-sm text-gray-500">{detail}</div>
    );
  }

  const { driver_name, driver_id, rating, experience_years, base_location, license_type, license_expiry } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <DriverSummaryCard
          title={driver_name ?? driver_id}
          subtitle={[base_location, driver_id].filter(Boolean).join(" · ")}
          rating={rating}
          experienceYears={experience_years}
          licenseType={license_type}
          licenseExpiry={license_expiry}
          licenseExpiringSoon={data.license_expiring_soon}
          isOnTrip={data.is_on_trip}
        />
        <HosComplianceCard hosHistory={data.hos_history} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PerformanceCard
          totalTrips={data.total_trips}
          onTimeRate={data.on_time_rate}
          avgDelayMinutes={data.avg_delay_minutes}
          avgProfitMargin={data.avg_profit_margin}
          delayedTrips={data.delayed_trips}
        />
        <BehaviorCard
          speedingIncidents={data.behavior.speeding_incidents}
          harshBraking={data.behavior.harsh_braking_count}
          harshAccel={data.behavior.harsh_accel_count}
          violations={data.behavior.violation_count}
        />
      </div>

      <RecentTripsCard recentTrips={data.recent_trips} />
    </div>
  );
}

function DriverSummaryCard({
  title,
  subtitle,
  rating,
  experienceYears,
  licenseType,
  licenseExpiry,
  licenseExpiringSoon,
  isOnTrip,
}: {
  title: string;
  subtitle: string;
  rating: number | null;
  experienceYears: number | null;
  licenseType: string | null;
  licenseExpiry: string | null;
  licenseExpiringSoon: boolean | null;
  isOnTrip: boolean;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-gray-900">{title}</div>
          <div className="text-xs text-gray-500 mt-0.5 truncate">{subtitle}</div>
        </div>
        <span
          className={`px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap shrink-0 ${
            isOnTrip ? "bg-sky-50 text-sky-700" : "bg-gray-100 text-gray-500"
          }`}
        >
          {isOnTrip ? "On trip" : "Available"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-gray-100">
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase">Rating</div>
          <div className="text-lg font-semibold text-gray-900 mt-1">
            {rating != null ? `${rating.toFixed(1)} / 5` : "—"}
          </div>
        </div>
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase">Experience</div>
          <div className="text-lg font-semibold text-gray-900 mt-1">
            {experienceYears != null ? `${experienceYears} yrs` : "—"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 mt-4 pt-4 border-t border-gray-100">
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">License type</div>
          <div className="text-sm font-medium text-gray-900 mt-0.5">{licenseType ?? "—"}</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">License expires</div>
          <div className="text-sm font-medium text-gray-900 mt-0.5">{formatDate(licenseExpiry)}</div>
          {licenseExpiringSoon != null && (
            <div className="text-[10px] text-amber-600 mt-0.5">
              {licenseExpiringSoon ? "Expiring soon" : "Valid"}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function HosComplianceCard({ hosHistory }: { hosHistory: DriverHoursRead[] }) {
  const records = hosHistory.filter((h) => h.hours_driven != null || h.hos_compliant != null);
  const compliantRecords = records.filter((h) => h.hos_compliant === true).length;
  const totalHours = records.reduce((sum, h) => sum + (h.hours_driven ?? 0), 0);
  const compliancePct = records.length > 0 ? (compliantRecords / records.length) * 100 : null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-start justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Hours of service</h3>
        <span
          className={`px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
            compliancePct == null
              ? "bg-gray-100 text-gray-500"
              : compliancePct >= 90
                ? "bg-emerald-50 text-emerald-700"
                : "bg-amber-50 text-amber-700"
          }`}
        >
          {compliancePct != null ? `${Math.round(compliancePct)}% compliant` : "No records"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-gray-100">
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase">Hours driven (14d)</div>
          <div className="text-lg font-semibold text-gray-900 mt-1">{totalHours.toFixed(1)}h</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase">Days recorded</div>
          <div className="text-lg font-semibold text-gray-900 mt-1">{records.length}</div>
        </div>
      </div>

      {compliancePct != null && (
        <>
          <div className="mt-3 h-2 rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full rounded-full ${compliancePct >= 90 ? "bg-teal-600" : "bg-amber-500"}`}
              style={{ width: `${Math.min(compliancePct, 100)}%` }}
            />
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {compliantRecords} of {records.length} recorded days fully HOS-compliant
          </div>
        </>
      )}

      {hosHistory.length > 0 && (
        <div className="mt-4 pt-3 border-t border-gray-100 space-y-1.5 max-h-44 overflow-y-auto">
          {hosHistory.map((h, i) => (
            <div key={`${h.date ?? i}-${i}`} className="flex items-center justify-between text-xs">
              <span className="text-gray-500">{h.date ?? "—"}</span>
              <span className="text-gray-700">
                {h.trips_count != null && `${h.trips_count} trips · `}
                {h.hours_driven != null ? `${h.hours_driven}h` : "—"}
              </span>
              <span
                className={`font-medium ${
                  h.hos_compliant == null
                    ? "text-gray-400"
                    : h.hos_compliant
                      ? "text-emerald-600"
                      : "text-red-600"
                }`}
              >
                {h.hos_compliant == null ? "n/a" : h.hos_compliant ? "Compliant" : "Violation"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PerformanceCard({
  totalTrips,
  onTimeRate,
  avgDelayMinutes,
  avgProfitMargin,
  delayedTrips,
}: {
  totalTrips: number;
  onTimeRate: number | null;
  avgDelayMinutes: number | null;
  avgProfitMargin: number | null;
  delayedTrips: number;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Performance</h3>
      <p className="text-xs text-gray-500 mt-0.5 mb-4">Across resolved trips (Delivered / Delayed)</p>

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">Total trips</div>
          <div className="text-lg font-semibold text-gray-900 mt-0.5">{totalTrips}</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">On-time rate</div>
          <div className="text-lg font-semibold mt-0.5 text-emerald-600">{formatPercent(onTimeRate)}</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">Avg delay (when delayed)</div>
          <div className="text-lg font-semibold mt-0.5 text-amber-600">{formatDuration(avgDelayMinutes)}</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">Avg profit margin</div>
          <div className="text-lg font-semibold mt-0.5 text-gray-900">
            {avgProfitMargin != null ? `${avgProfitMargin.toFixed(1)}%` : "—"}
          </div>
        </div>
      </div>

      <p className="text-xs text-gray-400 mt-3">
        {totalTrips > 0
          ? `${delayedTrips} of ${totalTrips} resolved trips ran late`
          : "No resolved trips on record yet — stats populate as trips complete."}
      </p>
    </div>
  );
}

const BEHAVIOR_ROWS = [
  { key: "speeding", label: "Speeding incidents", color: "bg-red-500", compare: "incidents" as const },
  { key: "braking", label: "Harsh braking events", color: "bg-amber-500", compare: "events" as const },
  { key: "accel", label: "Harsh acceleration events", color: "bg-sky-500", compare: "events" as const },
  { key: "violations", label: "Violations", color: "bg-violet-500", compare: "violations" as const },
];

function BehaviorCard({
  speedingIncidents,
  harshBraking,
  harshAccel,
  violations,
}: {
  speedingIncidents: number;
  harshBraking: number;
  harshAccel: number;
  violations: number;
}) {
  const values: Record<string, number> = {
    speeding: speedingIncidents,
    braking: harshBraking,
    accel: harshAccel,
    violations,
  };
  const max = Math.max(...Object.values(values), 1);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Behavioral safety</h3>
      <p className="text-xs text-gray-500 mt-0.5 mb-4">Aggregate event counts across this driver's trips</p>
      <div className="space-y-3">
        {BEHAVIOR_ROWS.map((row) => {
          const value = values[row.key];
          return (
            <div key={row.key}>
              <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                <span>{row.label}</span>
                <span className="font-medium text-gray-700">
                  {value} {row.compare}
                </span>
              </div>
              <div className="h-3 rounded-full bg-gray-100 overflow-hidden">
                <div className={`h-full rounded-full ${row.color}`} style={{ width: `${Math.min((value / max) * 100, 100)}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      {max <= 1 && (
        <p className="text-xs text-gray-400 mt-3">
          No notable safety events recorded for this driver yet.
        </p>
      )}
    </div>
  );
}

function RecentTripsCard({ recentTrips }: { recentTrips: { trip_id: string; origin: string | null; destination: string | null; status: string | null; pickup_time: string | null; delay_minutes: number | null; profit_margin: number | null }[] }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Recent trips</h3>
      {recentTrips.length === 0 ? (
        <p className="text-xs text-gray-400 mt-2">No trips on record for this driver.</p>
      ) : (
        <div className="mt-2 space-y-0">
          {recentTrips.map((t) => (
            <div key={t.trip_id} className="flex items-center justify-between gap-3 py-2.5 border-b border-gray-100 last:border-b-0">
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-900 truncate">
                  {[t.origin, t.destination].filter(Boolean).join(" → ") || t.trip_id}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {formatDate(t.pickup_time)}
                  {t.delay_minutes != null && t.delay_minutes > 0 && (
                    <span className="text-amber-600"> · delayed {formatDuration(t.delay_minutes)}</span>
                  )}
                </div>
              </div>
              <div className="text-right shrink-0">
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                    t.status?.toLowerCase() === "delivered"
                      ? "bg-emerald-50 text-emerald-700"
                      : t.status?.toLowerCase() === "delayed"
                        ? "bg-amber-50 text-amber-700"
                        : "bg-gray-100 text-gray-500"
                  }`}
                >
                  {t.status ?? "—"}
                </span>
                <div className="text-xs text-gray-400 mt-1">
                  {t.profit_margin != null ? `${t.profit_margin.toFixed(1)}% margin` : "—"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}