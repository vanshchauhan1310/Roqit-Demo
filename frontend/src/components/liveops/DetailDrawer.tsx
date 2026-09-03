import { useQuery } from "@tanstack/react-query";
import { fetchTrip } from "@/api/trips";
import { fetchRoute } from "@/api/routes";
import type { Trip } from "@/types/trip";
import type { Route, RouteStop } from "@/types/route";

export type Selection = { type: "trip" | "route"; id: string } | null;

function fmt(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return isNaN(d.getTime()) ? v : d.toLocaleString();
}

function num(v: number | null | undefined, suffix = ""): string {
  return v == null ? "—" : `${v}${suffix}`;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 border-b border-gray-50 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900 text-right">{value}</span>
    </div>
  );
}

export function StatusPill({ status }: { status: string | null }) {
  const s = (status ?? "unknown").toLowerCase();
  const cls =
    s === "unassigned" || s === "received"
      ? "bg-amber-100 text-amber-800"
      : s === "assigned" || s === "scheduled" || s === "planned"
        ? "bg-blue-100 text-blue-800"
        : s === "in-transit" || s === "in_progress" || s === "active"
          ? "bg-teal-100 text-teal-800"
          : s === "completed"
            ? "bg-green-100 text-green-800"
            : "bg-gray-100 text-gray-700";
  return <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>{s}</span>;
}

function TripDetailBody({ trip, onOpenRoute }: { trip: Trip; onOpenRoute: (id: string) => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-gray-900">{trip.trip_id}</h3>
        <StatusPill status={trip.status} />
      </div>

      <div className="rounded-lg bg-gray-50 px-3 py-2.5 text-sm">
        <div className="font-medium text-gray-900">
          {trip.origin ?? "unknown"} <span className="text-gray-400">→</span> {trip.destination ?? "unknown"}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">
          {trip.gps_start_lat != null && `${trip.gps_start_lat.toFixed(4)}, ${trip.gps_start_lon?.toFixed(4)}`}
          {" → "}
          {trip.gps_end_lat != null && `${trip.gps_end_lat.toFixed(4)}, ${trip.gps_end_lon?.toFixed(4)}`}
        </div>
      </div>

      <div>
        <Field label="Load" value={num(trip.load_weight_kg, " kg")} />
        <Field label="Load value" value={trip.load_value != null ? `₹${trip.load_value}` : "—"} />
        <Field label="Vehicle" value={trip.vehicle_id ?? "not assigned"} />
        <Field label="Driver" value={trip.driver_name ?? trip.driver_id ?? "not assigned"} />
        <Field label="Vehicle type" value={trip.vehicle_type ?? "—"} />
        <Field label="Planned distance" value={num(trip.planned_distance_km, " km")} />
        <Field label="Actual distance" value={num(trip.actual_distance_km, " km")} />
        <Field label="Pickup time" value={fmt(trip.pickup_time)} />
        <Field label="Planned delivery" value={fmt(trip.planned_delivery_time)} />
        <Field label="Actual delivery" value={fmt(trip.actual_delivery_time)} />
        <Field label="Delay" value={trip.delay_minutes != null ? `${trip.delay_minutes} min` : "—"} />
        <Field label="Traffic" value={trip.traffic_density ?? "—"} />
        <Field label="Weather" value={trip.weather_condition ?? "—"} />
      </div>

      {trip.route_id ? (
        <button
          onClick={() => onOpenRoute(trip.route_id as string)}
          className="w-full rounded-lg bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-700"
        >
          View assigned route →
        </button>
      ) : (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
          Waiting in the assignment queue — the engine will insert this trip into
          the best feasible route (or create a new one) automatically.
        </div>
      )}
    </div>
  );
}

function TripDetail({ tripId, onOpenRoute }: { tripId: string; onOpenRoute: (id: string) => void }) {
  const { data: trip, isLoading, error } = useQuery<Trip, Error>({
    queryKey: ["liveops-trip", tripId],
    queryFn: () => fetchTrip(tripId),
    refetchInterval: 8000,
    // Short retry window: without this a failing request retries 3x with
    // exponential backoff, which reads as an endless "Loading trip...".
    retry: 1,
    retryDelay: 500,
    staleTime: 5000,
  });
  if (isLoading) return <p className="text-sm text-gray-400 py-6 text-center">Loading trip…</p>;
  if (error || !trip) return <p className="text-sm text-red-500 py-6 text-center">Could not load trip details</p>;
  return <TripDetailBody trip={trip} onOpenRoute={onOpenRoute} />;
}

function RouteDetail({ routeId, onOpenTrip }: { routeId: string; onOpenTrip: (id: string) => void }) {
  const { data: route, isLoading, error } = useQuery<Route, Error>({
    queryKey: ["liveops-route", routeId],
    queryFn: () => fetchRoute(routeId),
    refetchInterval: 8000,
    retry: 1,
    retryDelay: 500,
    staleTime: 5000,
  });
  if (isLoading) return <p className="text-sm text-gray-400 py-6 text-center">Loading route…</p>;
  if (error || !route) return <p className="text-sm text-red-500 py-6 text-center">Could not load route details</p>;
  return <RouteDetailBody route={route} onOpenTrip={onOpenTrip} />;
}

/** Right-hand slide-over showing full details of the selected trip or route. */
export function DetailDrawer({
  selection,
  onSelect,
  onClose,
}: {
  selection: Selection;
  onSelect: (s: Selection) => void;
  onClose: () => void;
}) {
  const open = selection != null;

  return (
    <>
      {/* backdrop */}
      <div
        onClick={onClose}
        className={`fixed inset-0 z-[1200] bg-black/30 transition-opacity ${
          open ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      />
      {/* panel */}
      <aside
        className={`fixed top-0 right-0 z-[1300] h-full w-[430px] max-w-[92vw] bg-white shadow-2xl border-l border-gray-200
          transition-transform duration-200 ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            {selection?.type === "route" ? "Route details" : "Trip details"}
          </span>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full hover:bg-gray-100 text-gray-500 text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="h-[calc(100%-49px)] overflow-y-auto px-4 py-4">
          {selection?.type === "trip" && (
            <TripDetail tripId={selection.id} onOpenRoute={(id) => onSelect({ type: "route", id })} />
          )}
          {selection?.type === "route" && (
            <RouteDetail routeId={selection.id} onOpenTrip={(id) => onSelect({ type: "trip", id })} />
          )}
          {!selection && <p className="text-sm text-gray-400 text-center py-6">Nothing selected</p>}
        </div>
      </aside>
    </>
  );
}

function RouteDetailBody({ route, onOpenTrip }: { route: Route; onOpenTrip: (id: string) => void }) {
  const stops: RouteStop[] = [...(route.stops ?? [])].sort((a, b) => a.sequence - b.sequence);
  const capPct =
    route.capacity_kg && route.used_capacity_kg != null
      ? Math.min(100, Math.round((route.used_capacity_kg / route.capacity_kg) * 100))
      : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-gray-900">{route.name ?? route.route_id.slice(0, 12)}</h3>
        <StatusPill status={route.status} />
      </div>

      <div>
        <Field label="Vehicle" value={route.vehicle_id ?? "—"} />
        <Field label="Driver" value={route.driver_id ?? "—"} />
        <Field label="Created" value={fmt(route.created_at)} />
        <Field label="Stops" value={String(stops.length)} />
      </div>

      {capPct != null && (
        <div>
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>Capacity</span>
            <span>
              {route.used_capacity_kg}/{route.capacity_kg} kg · {capPct}%
            </span>
          </div>
          <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full rounded-full ${capPct > 90 ? "bg-red-500" : capPct > 70 ? "bg-amber-500" : "bg-teal-500"}`}
              style={{ width: `${capPct}%` }}
            />
          </div>
        </div>
      )}

      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Stop sequence</h4>
        <div className="space-y-1.5">
          {stops.map((s) => (
            <button
              key={s.stop_id}
              onClick={() => s.trip_id && onOpenTrip(s.trip_id)}
              disabled={!s.trip_id}
              className={`w-full text-left rounded-lg border px-3 py-2 flex items-center gap-3 ${
                s.trip_id ? "border-gray-200 hover:border-teal-400 hover:bg-teal-50/40" : "border-gray-100"
              }`}
            >
              <span className="w-6 h-6 shrink-0 rounded-full bg-gray-900 text-white text-[11px] font-bold flex items-center justify-center">
                {s.sequence}
              </span>
              <span className="flex-1 min-w-0">
                <span className="block text-sm font-medium text-gray-900 capitalize">
                  {s.stop_type}
                  {s.trip_id && <span className="text-gray-400 font-normal"> · {s.trip_id}</span>}
                </span>
                <span className="block text-xs text-gray-500 truncate">{s.address ?? "—"}</span>
              </span>
              <span className="text-xs text-gray-400 shrink-0">ETA {fmt(s.eta).split(",")[1] ?? "—"}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}