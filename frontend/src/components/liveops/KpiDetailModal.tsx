import { useEffect, useMemo } from "react";
import type { Trip } from "@/types/trip";
import type { Route } from "@/types/route";

export type KpiDetailView = "queue" | "trips" | "routes";

interface KpiDetailModalProps {
  view: KpiDetailView;
  incoming: Trip[];
  allTrips: Trip[];
  routes: Route[];
  onClose: () => void;
  onOpenTrip: (tripId: string) => void;
  onOpenRoute: (routeId: string) => void;
}

const VIEW_META: Record<KpiDetailView, { title: string; blurb: string }> = {
  queue: {
    title: "Queue depth — unassigned trips",
    blurb:
      "Trips with no route assignment yet. The engine picks these up continuously; when the auto-feed is off and the fleet has duty hours left, this list drains to zero.",
  },
  trips: {
    title: "Trips today — full breakdown",
    blurb:
      "Every trip in the system grouped by lifecycle stage. Click any trip to open its detail drawer.",
  },
  routes: {
    title: "Active routes",
    blurb:
      "All live routes created by the engine (planned / active / in-transit). Click a route to open it in the detail drawer.",
  },
};

function statusBucket(
  status: string | null | undefined,
): "completed" | "in-transit" | "scheduled" | "unassigned" | "other" {
  const s = (status ?? "").toLowerCase();
  if (s === "delivered" || s === "completed") return "completed";
  if (s === "in-transit" || s === "in_transit" || s === "in transit")
    return "in-transit";
  if (s === "scheduled") return "scheduled";
  if (s === "unassigned") return "unassigned";
  return "other";
}

const BUCKET_META: {
  key: ReturnType<typeof statusBucket>;
  label: string;
  tone: string;
  desc: string;
}[] = [
  {
    key: "completed",
    label: "Completed",
    tone: "text-emerald-300",
    desc: "Delivered. Its cargo weight has been released back to the vehicle.",
  },
  {
    key: "in-transit",
    label: "In transit",
    tone: "text-sky-300",
    desc: "On the road right now - attached to an active route and moving.",
  },
  {
    key: "scheduled",
    label: "Scheduled",
    tone: "text-slate-300",
    desc: "Assigned to a route and vehicle, waiting for pickup. Auto-completes 10 minutes after assignment.",
  },
  {
    key: "unassigned",
    label: "Unassigned",
    tone: "text-amber-300",
    desc: "Not routed yet - sitting in the queue until the engine finds a feasible vehicle with enough free capacity and driver hours. Shrinks as trips complete and capacity frees up.",
  },
];

function TripRow({
  trip,
  onOpenTrip,
}: {
  trip: Trip;
  onOpenTrip: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onOpenTrip(trip.trip_id)}
      className="w-full grid grid-cols-[110px_1fr_90px_90px] gap-2 items-center px-3 py-2 text-left text-[11px] hover:bg-slate-800/70 rounded-lg"
    >
      <span className="tnum text-slate-200 font-medium">{trip.trip_id}</span>
      <span className="truncate text-slate-400">
        {trip.origin ?? "?"} → {trip.destination ?? "?"}
      </span>
      <span className="tnum text-slate-400">
        {trip.load_weight_kg != null ? `${trip.load_weight_kg} kg` : "—"}
      </span>
      <span className="text-slate-500 truncate">{trip.status ?? "—"}</span>
    </button>
  );
}

export function KpiDetailModal({
  view,
  incoming,
  allTrips,
  routes,
  onClose,
  onOpenTrip,
  onOpenRoute,
}: KpiDetailModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const buckets = useMemo(() => {
    const by = {
      completed: [] as Trip[],
      "in-transit": [] as Trip[],
      scheduled: [] as Trip[],
      unassigned: [] as Trip[],
      other: [] as Trip[],
    };
    for (const t of allTrips) by[statusBucket(t.status)].push(t);
    return by;
  }, [allTrips]);

  const meta = VIEW_META[view];

  return (
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-slate-950/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[80vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-5 py-4">
          <div>
            <h2 className="text-sm font-bold uppercase tracking-[0.12em] text-slate-200">
              {meta.title}
            </h2>
            <p className="mt-1 text-[11px] leading-snug text-slate-500">
              {meta.blurb}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-slate-700 px-2.5 py-1 text-[11px] font-semibold text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          >
            Esc ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-3 py-3">
          {view === "queue" &&
            (incoming.length === 0 ? (
              <div className="px-4 py-10 text-center text-[12px] text-emerald-300">
                ✓ Queue is empty — every trip has been assigned to a route.
              </div>
            ) : (
              <div className="space-y-0.5">
                <div className="grid grid-cols-[110px_1fr_90px_90px] gap-2 px-3 pb-1 text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">
                  <span>Trip</span>
                  <span>Lane</span>
                  <span>Load</span>
                  <span>Status</span>
                </div>
                {incoming.map((t) => (
                  <TripRow key={t.trip_id} trip={t} onOpenTrip={onOpenTrip} />
                ))}
              </div>
            ))}

          {view === "trips" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2 px-2">
                {BUCKET_META.map((b) => (
                  <div
                    key={b.key}
                    title={b.desc}
                    className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2"
                  >
                    <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
                      {b.label}
                    </div>
                    <div className={`tnum text-xl font-bold ${b.tone}`}>
                      {buckets[b.key].length}
                    </div>
                    <div className="mt-1 text-[8.5px] leading-snug text-slate-500">
                      {b.desc}
                    </div>
                  </div>
                ))}
                <div
                  title="Any other lifecycle status reported by the system."
                  className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2"
                >
                  <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
                    Other
                  </div>
                  <div className="tnum text-xl font-bold text-slate-400">
                    {buckets.other.length}
                  </div>
                  <div className="mt-1 text-[8.5px] leading-snug text-slate-500">
                    Any other lifecycle status reported by the system.
                  </div>
                </div>
              </div>
              {BUCKET_META.filter((b) => buckets[b.key].length > 0).map((b) => (
                <div key={b.key}>
                  <div
                    className={`px-3 pb-1 text-[10px] font-bold uppercase tracking-[0.14em] ${b.tone}`}
                  >
                    {b.label} · {buckets[b.key].length}
                  </div>
                  <div className="space-y-0.5">
                    {buckets[b.key].map((t) => (
                      <TripRow
                        key={t.trip_id}
                        trip={t}
                        onOpenTrip={onOpenTrip}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {view === "routes" &&
            (routes.length === 0 ? (
              <div className="px-4 py-10 text-center text-[12px] text-slate-500">
                No routes yet — the engine opens one as soon as a trip can't fit
                an existing route.
              </div>
            ) : (
              <div className="space-y-0.5">
                <div className="grid grid-cols-[1fr_110px_70px_1fr] gap-2 px-3 pb-1 text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">
                  <span>Route</span>
                  <span>Vehicle</span>
                  <span>Stops</span>
                  <span>Capacity used</span>
                </div>
                {routes.map((r) => {
                  const cap = r.capacity_kg ?? 0;
                  const used = r.used_capacity_kg ?? 0;
                  const pct = cap > 0 ? Math.round((used / cap) * 100) : 0;
                  return (
                    <button
                      key={r.route_id}
                      onClick={() => onOpenRoute(r.route_id)}
                      className="w-full grid grid-cols-[1fr_110px_70px_1fr] gap-2 items-center px-3 py-2 text-left text-[11px] hover:bg-slate-800/70 rounded-lg"
                    >
                      <span className="truncate text-slate-200 font-medium">
                        {r.name ?? r.route_id.slice(0, 8)}
                        <span className="ml-2 text-[10px] text-slate-500">
                          {r.status ?? ""}
                        </span>
                      </span>
                      <span className="truncate text-slate-400">
                        {r.vehicle_id ?? "—"}
                      </span>
                      <span className="tnum text-slate-400">
                        {r.stops?.length ?? 0}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="h-1.5 flex-1 rounded-full bg-slate-800 overflow-hidden">
                          <span
                            className={`block h-full rounded-full ${pct > 90 ? "bg-rose-400" : pct > 60 ? "bg-amber-400" : "bg-emerald-400"}`}
                            style={{ width: `${Math.min(100, pct)}%` }}
                          />
                        </span>
                        <span className="tnum text-slate-500 w-10 text-right">
                          {pct}%
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
        </div>

        {/* Footer */}
        <div className="border-t border-slate-800 px-5 py-2.5 text-[10px] text-slate-600">
          {view === "queue" &&
            `${incoming.length} trip(s) waiting for assignment`}
          {view === "trips" && `${allTrips.length} trip(s) total in the system`}
          {view === "routes" && `${routes.length} route(s) live`}
          {" · "}click a row to open its detail drawer
        </div>
      </div>
    </div>
  );
}
