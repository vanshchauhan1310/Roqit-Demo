import { useEffect, useRef, useState } from "react";
import type { Route } from "@/types/route";
import { colorForRouteId } from "@/utils/routeColors";

/**
 * Plan-builder strip: for every active route, shows the stop sequence as
 * chips that POP IN as the engine inserts them — so you literally watch
 * the plan being constructed over time.
 */
export function PlanStrip({
  routes,
  onOpenRoute,
  selectedRouteId,
}: {
  routes: Route[];
  onOpenRoute: (id: string) => void;
  selectedRouteId: string | null;
}) {
  const seenStopsRef = useRef<Set<string>>(new Set());
  const [freshStops, setFreshStops] = useState<Set<string>>(new Set());
  const initializedRef = useRef(false);

  useEffect(() => {
    const all = new Set<string>();
    for (const r of routes) for (const s of r.stops ?? []) all.add(s.stop_id);
    if (!initializedRef.current) {
      seenStopsRef.current = all;
      initializedRef.current = true;
      return;
    }
    const fresh = new Set<string>();
    for (const id of all) if (!seenStopsRef.current.has(id)) fresh.add(id);
    seenStopsRef.current = all;
    if (fresh.size > 0) {
      setFreshStops(fresh);
      const t = setTimeout(() => setFreshStops(new Set()), 1500);
      return () => clearTimeout(t);
    }
  }, [routes]);

  const active = routes.filter((r) => (r.stops?.length ?? 0) > 0).slice(0, 8);
  if (active.length === 0) return null;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
      <div className="flex items-center justify-between mb-2 px-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Plan Builder — stops sequenced by the engine
        </h2>
        <span className="text-[10px] text-slate-500">pickup ● P · delivery ● D · click a chip for details</span>
      </div>
      <div className="space-y-1.5 max-h-[132px] overflow-y-auto ops-scroll pr-1">
        {active.map((r) => {
          const color = colorForRouteId(r.route_id);
          const capPct =
            r.capacity_kg && r.used_capacity_kg != null
              ? Math.min(100, Math.round((r.used_capacity_kg / r.capacity_kg) * 100))
              : null;
          return (
            <button
              key={r.route_id}
              onClick={() => onOpenRoute(r.route_id)}
              className={`w-full flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors ${
                selectedRouteId === r.route_id
                  ? "bg-slate-800 ring-1 ring-teal-500/50"
                  : "bg-slate-800/40 hover:bg-slate-800"
              }`}
            >
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
              <span className="text-[11px] font-medium text-slate-300 w-28 truncate shrink-0">
                {r.name ?? r.route_id.slice(0, 8)}
              </span>
              <span className="flex-1 flex items-center gap-1 overflow-x-auto ops-scroll py-0.5">
                {[...(r.stops ?? [])]
                  .sort((a, b) => a.sequence - b.sequence)
                  .map((s) => {
                    const frozen = (r.frozen_until_sequence ?? 0) >= (s.sequence ?? 0);
                    return (
                      <span
                        key={s.stop_id}
                        title={`#${s.sequence} ${s.stop_type}${s.trip_id ? ` · ${s.trip_id}` : ""}${
                          frozen ? " · 🔒 frozen (LNS can't touch this leg)" : ""
                        }`}
                        className={`shrink-0 w-5 h-5 rounded-md text-[9px] font-bold flex items-center justify-center border ${
                          s.stop_type === "pickup"
                            ? "bg-slate-950 text-slate-200 border-slate-600"
                            : "bg-slate-800 text-slate-400 border-slate-700"
                        } ${frozen ? "opacity-45" : ""} ${
                          freshStops.has(s.stop_id) ? "chip-pop ring-1 ring-teal-400" : ""
                        }`}
                      >
                        {s.stop_type === "pickup" ? "P" : "D"}
                      </span>
                    );
                  })}
                {((r.stops ?? []).length > 0) && (r.frozen_until_sequence ?? 0) > 0 && (
                  <span
                    className="shrink-0 rounded px-1 py-0.5 text-[9px] border border-slate-700 text-slate-500"
                    title={`First ${r.frozen_until_sequence} stop(s) frozen — in-progress legs LNS will not re-plan`}
                  >
                    🔒 {r.frozen_until_sequence}
                  </span>
                )}
              </span>
              {capPct != null && (
                <span className="hidden xl:flex items-center gap-1.5 w-24 shrink-0">
                  <span className="flex-1 h-1 rounded-full bg-slate-800 overflow-hidden">
                    <span
                      className="block h-full rounded-full"
                      style={{ width: `${capPct}%`, backgroundColor: capPct > 90 ? "#f87171" : color }}
                    />
                  </span>
                  <span className="text-[9px] text-slate-500 tnum w-8 text-right">{capPct}%</span>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}