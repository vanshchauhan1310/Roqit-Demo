import { Trip } from "@/types/trip";
import { useVehicleIntelligence } from "@/hooks/useVehicleIntelligence";
import type { FuelEfficiencyComparison, MaintenanceBadge, MaintenanceEventItem } from "@/types/vehicleIntelligence";

interface VehicleIntelligenceTabProps {
  trip: Trip;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

function formatNumber(value: number | null, suffix = ""): string {
  return value != null ? `${value.toLocaleString()}${suffix}` : "—";
}

function formatCurrency(value: number | null): string {
  return value != null ? `₹${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—";
}

export function VehicleIntelligenceTab({ trip }: VehicleIntelligenceTabProps) {
  const { data, isLoading, isError, error } = useVehicleIntelligence(trip.trip_id);

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading vehicle intelligence…</p>;
  }

  if (isError || !data) {
    const detail =
      (error as { response?: { data?: { detail?: string } } } | undefined)?.response?.data?.detail ??
      "No vehicle intelligence available for this trip.";
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6 text-sm text-gray-500">{detail}</div>
    );
  }

  const { vehicle, load, fuel_efficiency, maintenance, cost } = data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <VehicleSummaryCard
          title={`${vehicle.make ?? ""} ${vehicle.model ?? ""}`.trim() || vehicle.vehicle_id}
          subtitle={[vehicle.vehicle_type, vehicle.vehicle_id].filter(Boolean).join(" · ")}
          assigned={vehicle.assigned}
          odometerKm={vehicle.odometer_km}
          loadCapacityKg={load.load_capacity_kg}
          loadWeightKg={load.load_weight_kg}
          utilizationPct={load.utilization_pct}
        />
        <FuelEfficiencyCard fuelEfficiency={fuel_efficiency} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <MaintenanceStatusCard
          lastServiceDate={maintenance.last_service_date}
          nextServiceDueKm={maintenance.next_service_due_km}
          pctIntervalConsumed={maintenance.pct_interval_consumed}
          status={maintenance.status}
        />
        <CostSnapshotCard
          fuelCost={cost.fuel_cost}
          maintenanceCost={cost.maintenance_cost}
          tollCost={cost.toll_cost}
          fuelCostIsEstimate={cost.fuel_cost_is_estimate}
          maintenanceCostIsEstimate={cost.maintenance_cost_is_estimate}
          tollCostIsEstimate={cost.toll_cost_is_estimate}
          tripTco={cost.trip_tco}
          tripCostPerKm={cost.trip_cost_per_km}
          fleetAvgCostPerKm={cost.fleet_avg_cost_per_km}
        />
      </div>

      <MaintenanceHistoryCard history={maintenance.history} />
    </div>
  );
}

function VehicleSummaryCard({
  title,
  subtitle,
  assigned,
  odometerKm,
  loadCapacityKg,
  loadWeightKg,
  utilizationPct,
}: {
  title: string;
  subtitle: string;
  assigned: boolean;
  odometerKm: number | null;
  loadCapacityKg: number | null;
  loadWeightKg: number | null;
  utilizationPct: number | null;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-sm font-semibold text-gray-900">{title}</div>
          <div className="text-xs text-gray-500 mt-0.5">{subtitle}</div>
        </div>
        <span
          className={`px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
            assigned ? "bg-sky-50 text-sky-700" : "bg-gray-100 text-gray-500"
          }`}
        >
          {assigned ? "Assigned" : "Unassigned"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-gray-100">
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase">Odometer</div>
          <div className="text-lg font-semibold text-gray-900 mt-1">{formatNumber(odometerKm, " km")}</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase">Load capacity utilization</div>
          <div className="text-lg font-semibold text-gray-900 mt-1">{utilizationPct != null ? `${utilizationPct}%` : "—"}</div>
        </div>
      </div>

      {loadCapacityKg != null && (
        <>
          <div className="mt-2 h-2 rounded-full bg-gray-100 overflow-hidden">
            <div
              className="h-full bg-teal-600 rounded-full"
              style={{ width: `${Math.min(utilizationPct ?? 0, 100)}%` }}
            />
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {formatNumber(loadWeightKg, " kg")} of {formatNumber(loadCapacityKg, " kg")}
          </div>
        </>
      )}
    </div>
  );
}

function EfficiencyBar({
  label,
  value,
  max,
  colorClass,
  isEstimate,
}: {
  label: string;
  value: number | null;
  max: number;
  colorClass: string;
  isEstimate?: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
        <span>
          {label}
          {isEstimate && value != null && <span className="text-gray-400"> (estimated)</span>}
        </span>
        <span className="font-medium text-gray-700">{value != null ? `${value} L` : "no data"}</span>
      </div>
      <div className="h-3 rounded-full bg-gray-100 overflow-hidden">
        {value != null && (
          <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${Math.min((value / max) * 100, 100)}%` }} />
        )}
      </div>
    </div>
  );
}

function FuelEfficiencyCard({ fuelEfficiency }: { fuelEfficiency: FuelEfficiencyComparison }) {
  const { this_trip_fuel_l, this_trip_fuel_l_is_estimate, predicted_fuel_l, rated_fuel_l, fleet_avg_fuel_l } = fuelEfficiency;
  const max = Math.max(this_trip_fuel_l ?? 0, predicted_fuel_l ?? 0, rated_fuel_l ?? 0, fleet_avg_fuel_l ?? 0, 1) * 1.15;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Fuel efficiency comparison</h3>
      <p className="text-xs text-gray-500 mt-0.5 mb-4">Liters for this trip vs. predicted vs. rated vs. fleet average</p>
      <div className="space-y-3">
        <EfficiencyBar
          label="This trip (actual)"
          value={this_trip_fuel_l}
          max={max}
          colorClass="bg-red-500"
          isEstimate={this_trip_fuel_l_is_estimate}
        />
        <EfficiencyBar label="Predicted (ML)" value={predicted_fuel_l} max={max} colorClass="bg-violet-500" />
        <EfficiencyBar label="Rated" value={rated_fuel_l} max={max} colorClass="bg-teal-600" />
        <EfficiencyBar label="Fleet avg (same vehicle type)" value={fleet_avg_fuel_l} max={max} colorClass="bg-teal-300" />
      </div>
      {this_trip_fuel_l == null && (
        <p className="text-xs text-gray-400 mt-3">
          "This trip (actual)" needs either recorded fuel consumption or a rated km/l figure to estimate from.
        </p>
      )}
    </div>
  );
}

const MAINTENANCE_BADGE_STYLE: Record<MaintenanceBadge, string> = {
  ok: "bg-emerald-50 text-emerald-700",
  needs_attention: "bg-amber-50 text-amber-700",
  overdue: "bg-red-50 text-red-600",
};

const MAINTENANCE_BADGE_LABEL: Record<MaintenanceBadge, string> = {
  ok: "On track",
  needs_attention: "Needs attention",
  overdue: "Overdue",
};

function MaintenanceStatusCard({
  lastServiceDate,
  nextServiceDueKm,
  pctIntervalConsumed,
  status,
}: {
  lastServiceDate: string | null;
  nextServiceDueKm: number | null;
  pctIntervalConsumed: number | null;
  status: MaintenanceBadge | null;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-start justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Maintenance status</h3>
        {status && (
          <span className={`px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${MAINTENANCE_BADGE_STYLE[status]}`}>
            {MAINTENANCE_BADGE_LABEL[status]}
          </span>
        )}
      </div>
      <div className="mt-4 space-y-1">
        <div className="text-sm text-gray-600">
          Last service <span className="font-medium text-gray-900">{formatDate(lastServiceDate)}</span>
        </div>
        <div className="text-sm text-gray-600">
          Next service due <span className="font-medium text-gray-900">{formatNumber(nextServiceDueKm, " km")}</span>
        </div>
      </div>
      {pctIntervalConsumed != null ? (
        <>
          <div className="mt-3 h-2 rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full rounded-full ${
                status === "overdue" ? "bg-red-500" : status === "needs_attention" ? "bg-amber-500" : "bg-teal-600"
              }`}
              style={{ width: `${Math.min(pctIntervalConsumed, 100)}%` }}
            />
          </div>
          <div className="text-xs text-gray-400 mt-1">{pctIntervalConsumed}% of service interval consumed</div>
        </>
      ) : (
        <p className="text-xs text-gray-400 mt-3">
          No prior service record on file — interval progress can't be calculated yet.
        </p>
      )}
    </div>
  );
}

function CostSnapshotCard({
  fuelCost,
  maintenanceCost,
  tollCost,
  fuelCostIsEstimate,
  maintenanceCostIsEstimate,
  tollCostIsEstimate,
  tripTco,
  tripCostPerKm,
  fleetAvgCostPerKm,
}: {
  fuelCost: number | null;
  maintenanceCost: number | null;
  tollCost: number | null;
  fuelCostIsEstimate: boolean;
  maintenanceCostIsEstimate: boolean;
  tollCostIsEstimate: boolean;
  tripTco: number | null;
  tripCostPerKm: number | null;
  fleetAvgCostPerKm: number | null;
}) {
  const deltaPct =
    tripCostPerKm != null && fleetAvgCostPerKm
      ? Math.round(((tripCostPerKm - fleetAvgCostPerKm) / fleetAvgCostPerKm) * 100)
      : null;
  const anyEstimate = fuelCostIsEstimate || maintenanceCostIsEstimate || tollCostIsEstimate;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Cost snapshot</h3>
      <p className="text-xs text-gray-500 mt-0.5 mb-4">
        {anyEstimate ? "Recorded where available, estimated otherwise" : "This trip's real recorded costs"}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <CostTile label="Fuel" value={formatCurrency(fuelCost)} isEstimate={fuelCostIsEstimate} />
        <CostTile label="Maintenance" value={formatCurrency(maintenanceCost)} isEstimate={maintenanceCostIsEstimate} />
        <CostTile label="Tolls" value={formatCurrency(tollCost)} isEstimate={tollCostIsEstimate} />
        <CostTile label="Trip TCO" value={formatCurrency(tripTco)} isEstimate={anyEstimate} />
      </div>
      {deltaPct != null ? (
        <p className="text-xs text-gray-400 mt-3">
          Cost per km is{" "}
          <span className={deltaPct <= 0 ? "text-emerald-600 font-medium" : "text-red-600 font-medium"}>
            {deltaPct > 0 ? `${deltaPct}% above` : `${Math.abs(deltaPct)}% below`}
          </span>{" "}
          the fleet average (₹{fleetAvgCostPerKm}/km).
        </p>
      ) : (
        <p className="text-xs text-gray-400 mt-3">
          Fleet-average cost/km needs at least one other resolved trip with recorded costs.
        </p>
      )}
    </div>
  );
}

function CostTile({ label, value, isEstimate }: { label: string; value: string; isEstimate: boolean }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3">
      <div className="text-[10.5px] font-semibold tracking-wider text-gray-400 uppercase">{label}</div>
      <div className="text-lg font-semibold text-gray-900 mt-0.5">{value}</div>
      {isEstimate && value !== "—" && <div className="text-[10px] text-gray-400 mt-0.5">estimated</div>}
    </div>
  );
}

function MaintenanceHistoryCard({ history }: { history: MaintenanceEventItem[] }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900">Maintenance history</h3>
      {history.length === 0 ? (
        <p className="text-xs text-gray-400 mt-2">No maintenance events on file for this vehicle.</p>
      ) : (
        <div className="mt-2 space-y-0">
          {history.map((event) => (
            <div key={event.event_id} className="flex items-center justify-between gap-3 py-2.5 border-b border-gray-100 last:border-b-0">
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-900">{event.maintenance_type ?? "Service"}</div>
                <div className="text-xs text-gray-500 mt-0.5 truncate">
                  {formatDate(event.event_date)}
                  {event.odometer_at_service != null && ` · ${event.odometer_at_service.toLocaleString()} km`}
                  {event.description ? ` · ${event.description}` : ""}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-sm font-medium text-gray-900">{formatCurrency(event.cost)}</div>
                {event.downtime_hours != null && (
                  <div className="text-xs text-gray-400">{event.downtime_hours}h downtime</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
