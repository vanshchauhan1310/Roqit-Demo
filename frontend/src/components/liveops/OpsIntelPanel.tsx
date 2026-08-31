import { useMemo, useState } from "react";
import type { Trip } from "@/types/trip";
import type { Route } from "@/types/route";
import type { LnsRun } from "@/types/lns";
import type { Vehicle, Driver } from "@/api/fleet";
import { colorForRouteId } from "@/utils/routeColors";
import { downloadCsv } from "@/utils/exportCsv";

/* ---------- cost / distance helpers ---------- */

export function haversineKm(
  a: { latitude: number | null; longitude: number | null } | null | undefined,
  b: { latitude: number | null; longitude: number | null } | null | undefined,
): number {
  if (!a || !b || a.latitude == null || a.longitude == null || b.latitude == null || b.longitude == null) return 0;
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.latitude)) * Math.cos(toRad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

export function routeDistanceKm(route: Route): number {
  const geocoded = route.stops.filter((s) => s.latitude != null && s.longitude != null);
  let d = 0;
  for (let i = 1; i < geocoded.length; i++) d += haversineKm(geocoded[i - 1], geocoded[i]);
  return d;
}

export const DEFAULT_FUEL_PRICE = 92.5;

export interface CostRow {
  routeId: string;
  name: string;
  vehicleId: string | null;
  distKm: number;
  fuelCost: number;
  costPerKm: number;
  tonKm: number;
  costPerTonKm: number;
  stops: number;
  usedKg: number;
}

export function buildCostRows(routes: Route[], vehicles: Vehicle[]): CostRow[] {
  return routes.map((r) => {
    const v = vehicles.find((x) => x.vehicle_id === r.vehicle_id);
    const distKm = routeDistanceKm(r);
    const kmpl = v?.avg_kmpl_rated ?? 8.5;
    const fuelCost = (distKm / kmpl) * DEFAULT_FUEL_PRICE;
    const usedKg = r.used_capacity_kg ?? 0;
    const tonKm = (usedKg / 1000) * distKm;
    return {
      routeId: r.route_id,
      name: r.name ?? r.route_id.slice(0, 8),
      vehicleId: r.vehicle_id,
      distKm,
      fuelCost,
      costPerKm: distKm > 0 ? fuelCost / distKm : 0,
      tonKm,
      costPerTonKm: tonKm > 0 ? fuelCost / tonKm : 0,
      stops: r.stops?.length ?? 0,
      usedKg,
    };
  });
}

export const inr = (n: number) => `₹${n.toFixed(n >= 100 ? 0 : 1)}`;

/* ---------- per-vehicle utilization ---------- */

interface VehicleGauge {
  vehicle: Vehicle;
  usedKg: number;
  capacityKg: number;
  pct: number;
  routeIds: string[];
}

function buildGauges(routes: Route[], vehicles: Vehicle[]): VehicleGauge[] {
  const map = new Map<string, VehicleGauge>();
  for (const v of vehicles) {
    map.set(v.vehicle_id, {
      vehicle: v,
      usedKg: 0,
      capacityKg: v.load_capacity_kg ?? 0,
      pct: 0,
      routeIds: [],
    });
  }
  for (const r of routes) {
    if (!r.vehicle_id) continue;
    const g = map.get(r.vehicle_id);
    if (!g) continue;
    g.usedKg += r.used_capacity_kg ?? 0;
    g.routeIds.push(r.route_id);
    if (g.capacityKg > 0) g.pct = Math.min(100, Math.round((g.usedKg / g.capacityKg) * 100));
  }
  return [...map.values()];
}

function pctColor(pct: number): string {
  if (pct >= 90) return "#fb7185";
  if (pct >= 70) return "#fbbf24";
  return "#34d399";
}

/** Tab 1: per-vehicle utilization gauges + idle badges. */
function FleetTab({ routes, vehicles, onOpenRoute }: { routes: Route[]; vehicles: Vehicle[]; onOpenRoute: (id: string) => void }) {
  const gauges = useMemo(() => buildGauges(routes, vehicles), [routes, vehicles]);
  return (
    <div className="space-y-2">
      {gauges.length === 0 && <p className="text-xs text-slate-500">No vehicles registered yet.</p>}
      {gauges.map((g) => {
        const idle = g.routeIds.length === 0;
        return (
          <div key={g.vehicle.vehicle_id} className="rounded-lg border border-slate-800 bg-slate-900/60 px-3.5 py-3">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-200 tnum">{g.vehicle.vehicle_id}</span>
                <span className="rounded border border-slate-700 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-slate-400">
                  {g.vehicle.vehicle_type ?? "vehicle"}
                </span>
                {idle && (
                  <span className="rounded border border-amber-500/50 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300 bg-amber-500/10">
                    idle
                  </span>
                )}
              </div>
              <span className="tnum text-sm font-bold" style={{ color: pctColor(g.pct) }}>
                {g.pct}%
              </span>
            </div>
            <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${g.pct}%`, background: pctColor(g.pct) }}
              />
            </div>
            <div className="flex items-center justify-between mt-1.5 text-[10px] text-slate-500">
              <span className="tnum">
                {g.usedKg.toFixed(0)} / {g.capacityKg} kg
              </span>
              <span>
                {g.routeIds.length} active route{g.routeIds.length === 1 ? "" : "s"}
              </span>
            </div>
            {!idle && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {g.routeIds.map((rid) => (
                  <button
                    key={rid}
                    onClick={() => onOpenRoute(rid)}
                    className="flex items-center gap-1.5 rounded border border-slate-700 bg-slate-800/70 px-2 py-0.5 text-[10px] text-slate-300 hover:border-teal-500/50"
                  >
                    <span className="w-2 h-2 rounded-full" style={{ background: colorForRouteId(rid) }} />
                    <span className="tnum">{rid.slice(0, 8)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Tab 2: per-route cost estimates + CSV export. */
function CostsTab({ routes, vehicles }: { routes: Route[]; vehicles: Vehicle[] }) {
  const rows = useMemo(() => buildCostRows(routes, vehicles), [routes, vehicles]);
  const totals = rows.reduce(
    (a, r) => ({ km: a.km + r.distKm, fuel: a.fuel + r.fuelCost, tonKm: a.tonKm + r.tonKm }),
    { km: 0, fuel: 0, tonKm: 0 },
  );

  const exportCsv = () => {
    downloadCsv(
      `route-costs-${Date.now()}.csv`,
      ["route", "vehicle", "stops", "dist_km", "fuel_inr", "cost_per_km", "ton_km", "cost_per_ton_km", "used_kg"],
      rows.map((r) => [
        r.name,
        r.vehicleId,
        r.stops,
        r.distKm.toFixed(1),
        r.fuelCost.toFixed(1),
        r.costPerKm.toFixed(2),
        r.tonKm.toFixed(1),
        r.costPerTonKm.toFixed(2),
        r.usedKg,
      ]),
    );
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-slate-500 tnum">
          {rows.length} routes · {totals.km.toFixed(1)} km · {inr(totals.fuel)} est. fuel
        </span>
        <button
          onClick={exportCsv}
          className="rounded-md border border-teal-500/40 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-teal-300 hover:bg-teal-500/10"
        >
          ⬇ Export CSV
        </button>
      </div>
      <div className="rounded-lg border border-slate-800 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-900 text-slate-500 text-[9px] uppercase tracking-[0.12em]">
              <th className="text-left px-3 py-2">Route</th>
              <th className="text-left px-3 py-2">Vehicle</th>
              <th className="text-right px-3 py-2">Dist km</th>
              <th className="text-right px-3 py-2">Fuel ₹</th>
              <th className="text-right px-3 py-2">₹/km</th>
              <th className="text-right px-3 py-2">Ton-km</th>
              <th className="text-right px-3 py-2">₹/ton-km</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {rows.map((r) => (
              <tr key={r.routeId} className="bg-slate-950/60">
                <td className="px-3 py-2">
                  <span className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ background: colorForRouteId(r.routeId) }} />
                    <span className="text-slate-200">{r.name}</span>
                  </span>
                </td>
                <td className="px-3 py-2 tnum text-slate-400">{r.vehicleId ?? "—"}</td>
                <td className="px-3 py-2 text-right tnum text-slate-300">{r.distKm.toFixed(1)}</td>
                <td className="px-3 py-2 text-right tnum text-slate-200">{inr(r.fuelCost)}</td>
                <td className="px-3 py-2 text-right tnum text-slate-400">{r.costPerKm.toFixed(2)}</td>
                <td className="px-3 py-2 text-right tnum text-slate-400">{r.tonKm.toFixed(1)}</td>
                <td className="px-3 py-2 text-right tnum text-slate-400">{r.costPerTonKm.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Tab 3: per-driver scorecards. */
function DriversTab({ routes, trips, drivers }: { routes: Route[]; trips: Trip[]; drivers: Driver[] }) {
  // 14-hour duty clock rule: a driver has "used" hours proportional to the
  // number of stops they currently own on active routes. We approximate one
  // hour per 8 stops (≈ 7.5 stops/14h). A driver within 100% is green,
  // 100–130% is a 14-hour warning, >130% is a rule breach.
  const DRIVER_HOURS_LIMIT = 14;
  const STOPS_PER_DRIVER_HOUR = 8;

  const rows = useMemo(() => {
    return drivers.map((d) => {
      const myRoutes = routes.filter((r) => r.driver_id === d.driver_id);
      const myTrips = trips.filter((t) => t.driver_id === d.driver_id);
      // completed trips = assignments this driver has finished delivering
      const completedTrips = myTrips.filter((t) => t.status?.toLowerCase() === "completed");
      const completedRoutes = myRoutes.filter((r) => r.status?.toLowerCase() === "completed" || r.status?.toLowerCase() === "delivered");
      const stops = myRoutes.reduce((a, r) => a + (r.stops?.length ?? 0), 0);
      const delayed = myTrips.filter((t) => t.is_delayed === true).length;
      const onTime = myTrips.length ? ((myTrips.length - delayed) / myTrips.length) * 100 : null;
      const totalLoad = myTrips.reduce((a, t) => a + (t.load_weight_kg ?? 0), 0);

      // 14-hour service rule gauge
      const hoursOn = stops / STOPS_PER_DRIVER_HOUR;
      const pct = Math.min(100, Math.round((hoursOn / DRIVER_HOURS_LIMIT) * 100));
      const serviceWarning = hoursOn > DRIVER_HOURS_LIMIT;

      return {
        driver: d,
        routes: myRoutes.length,
        completedRoutes: completedRoutes.length,
        stops,
        completedStops: myRoutes.reduce((a, r) => a + (r.stops?.filter((s) => s.status?.toLowerCase() === "completed" || s.status?.toLowerCase() === "delivered").length ?? 0), 0),
        trips: myTrips.length,
        completedTrips: completedTrips.length,
        onTime,
        totalLoad,
        idle: myRoutes.length === 0 && myTrips.length === 0,
        serviceHours: hoursOn,
        servicePct: pct,
        serviceWarning,
      };
    });
  }, [routes, trips, drivers]);

  return (
    <div className="space-y-2">
      {rows.length === 0 && <p className="text-xs text-slate-500">No drivers registered yet.</p>}
      {rows.map((r) => (
        <div key={r.driver.driver_id} className="rounded-lg border border-slate-800 bg-slate-900/60 px-3.5 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center text-[11px] font-bold text-slate-200">
                {r.driver.driver_name?.slice(0, 1) ?? "?"}
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-200">{r.driver.driver_name}</div>
                <div className="text-[10px] text-slate-500 tnum">
                  {r.driver.driver_id} · {r.driver.base_location ?? "—"}
                  {r.driver.rating != null ? ` · ⭐ ${r.driver.rating.toFixed(1)}` : ""}
                </div>
              </div>
            </div>
            {r.idle && (
              <span className="rounded border border-amber-500/50 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300 bg-amber-500/10">
                idle
              </span>
            )}
            {r.serviceWarning && (
              <span className="rounded border border-rose-500/50 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-rose-300 bg-rose-500/10">
                14h rule
              </span>
            )}
          </div>

          {/* 14-hour service clock visual */}
          <div className="mt-2.5">
            <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
              <span>14-hour duty clock</span>
              <span className="tnum">
                {r.serviceHours.toFixed(1)}h / {DRIVER_HOURS_LIMIT}h
                {r.serviceWarning && <span className=" text-rose-400 ml-1.5">⚠ LIMIT</span>}
              </span>
            </div>
            <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
              <div
                className={`h-full rounded-full transition-colors ${
                  r.servicePct > 95 ? "bg-rose-500" : r.servicePct > 80 ? "bg-amber-400" : "bg-teal-400"
                }`}
                style={{ width: `${r.servicePct}%` }}
              />
            </div>
          </div>

          <div className="grid grid-cols-4 gap-2 mt-2.5 text-center">
            <Metric label="On-time %" value={r.onTime != null ? `${r.onTime.toFixed(0)}%` : "—"} accent={r.onTime != null && r.onTime < 80 ? "text-rose-300" : "text-teal-300"} />
            <Metric label="Routes" value={String(r.routes)} sub={r.completedRoutes !== r.routes ? `${r.completedRoutes} completed` : undefined} />
            <Metric label="Trips" value={String(r.completedTrips)} sub={r.trips !== r.completedTrips ? `${r.trips} total` : undefined} />
            <Metric label="Stops" value={String(r.stops)} sub={r.completedStops !== r.stops ? `${r.completedStops} completed` : undefined} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value, accent, sub }: { label: string; value: string; accent?: string; sub?: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/60 px-2 py-1.5">
      <div className="text-[8px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className={`tnum text-sm font-semibold ${accent ?? "text-slate-100"}`}>{value}</div>
      {sub && <div className="text-[9px] text-slate-500 tnum mt-0.25">{sub}</div>}
    </div>
  );
}

const TABS: { id: string; label: string; hint: string }[] = [
  { id: "fleet", label: "Fleet", hint: "vehicle utilization + idle" },
  { id: "costs", label: "Costs", hint: "fuel ₹ + export" },
  { id: "drivers", label: "Drivers", hint: "scorecards + 14h rule" },
];

export function OpsIntelPanel({
  open,
  routes,
  trips,
  vehicles,
  drivers,
  lnsRuns: _lnsRuns,
  latenciesSec: _latenciesSec,
  onClose,
  onOpenRoute,
}: {
  open: boolean;
  routes: Route[];
  trips: Trip[];
  vehicles: Vehicle[];
  drivers: Driver[];
  lnsRuns: LnsRun[];
  latenciesSec: number[];
  onClose: () => void;
  onOpenRoute: (routeId: string) => void;
}) {
  const [tab, setTab] = useState("fleet");

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[1200]">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="absolute top-0 right-0 z-[1300] h-full w-[620px] max-w-[95vw] bg-slate-950 border-l border-slate-700 shadow-2xl flex flex-col">
<div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800">
          <div>
            <h2 className="text-sm font-bold tracking-tight text-slate-100">
              OPS <span className="text-teal-400">INTEL</span>
            </h2>
            <p className="text-[10px] text-slate-500 mt-0.5">fleet · costs · drivers</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-500"
          >
            Close ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-5 py-2.5 border-b border-slate-800 overflow-x-auto ops-scroll">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`shrink-0 rounded-md border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.1em] ${
                tab === t.id
                  ? "border-teal-500/70 bg-teal-500/10 text-teal-200"
                  : "border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-500"
              }`}
              title={t.hint}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto ops-scroll px-5 py-4">
          {tab === "fleet" && <FleetTab routes={routes} vehicles={vehicles} onOpenRoute={onOpenRoute} />}
          {tab === "costs" && <CostsTab routes={routes} vehicles={vehicles} />}
          {tab === "drivers" && <DriversTab routes={routes} trips={trips} drivers={drivers} />}
        </div>
      </div>
    </div>
  );
}
