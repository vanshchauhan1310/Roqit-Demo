import { useMemo } from "react";
import type { Trip } from "@/types/trip";
import type { Route } from "@/types/route";
import type { LnsRun } from "@/types/lns";

interface AlertStripProps {
  incoming: Trip[];
  allTrips: Trip[];
  routes: Route[];
  lnsRuns: LnsRun[];
  onOpenTrip: (tripId: string) => void;
  onOpenRoute: (routeId: string) => void;
}

export function AlertStrip({ incoming, allTrips, routes, lnsRuns, onOpenTrip, onOpenRoute }: AlertStripProps) {
  const delayed = useMemo(() => allTrips.filter((t) => t.is_delayed === true), [allTrips]);

  const overCapacity = useMemo(
    () =>
      routes.filter((r) => {
        const used = r.used_capacity_kg ?? 0;
        const cap = r.capacity_kg ?? 0;
        return cap > 0 && used / cap > 0.9;
      }),
    [routes],
  );

  const savings = useMemo(() => {
    const accepted = lnsRuns.filter((r) => r.status === "completed" && (r.improvement ?? 0) > 0);
    const total = accepted.reduce((a, r) => a + (r.improvement ?? 0), 0);
    const lastPct = lnsRuns[0]?.improvement_pct ?? null;
    return { runs: accepted.length, total, lastPct };
  }, [lnsRuns]);

  const cards: {
    key: string;
    tone: "ok" | "warn" | "danger" | "info" | "accent";
    label: string;
    value: string;
    sub: string;
    onClick?: () => void;
  }[] = [];

  cards.push({
    key: "queue",
    tone: incoming.length > 0 ? "danger" : "ok",
    label: "Incoming queue",
    value: String(incoming.length),
    sub: incoming.length > 0 ? "waiting for assignment" : "all trips assigned",
    onClick: incoming.length > 0 ? () => onOpenTrip(incoming[0].trip_id) : undefined,
  });

  cards.push({
    key: "delayed",
    tone: delayed.length > 0 ? "warn" : "ok",
    label: "Delayed trips",
    value: String(delayed.length),
    sub: delayed.length > 0 ? "flagged by the engine" : "on schedule",
    onClick: delayed.length > 0 ? () => onOpenTrip(delayed[0].trip_id) : undefined,
  });

  cards.push({
    key: "capacity",
    tone: overCapacity.length > 0 ? "danger" : "ok",
    label: "Capacity >90%",
    value: String(overCapacity.length),
    sub: overCapacity.length > 0 ? "routes near the limit" : "all routes healthy",
    onClick: overCapacity.length > 0 ? () => onOpenRoute(overCapacity[0].route_id) : undefined,
  });

  cards.push({
    key: "routes",
    tone: "info",
    label: "Active routes",
    value: String(routes.length),
    sub: `${routes.reduce((a, r) => a + (r.stops?.length ?? 0), 0)} stops sequenced`,
  });

  cards.push({
    key: "savings",
    tone: "accent",
    label: "Engine savings",
    value:
      savings.lastPct != null && savings.lastPct > 0
        ? `−${Math.abs(savings.lastPct).toFixed(1)}%`
        : savings.runs > 0
          ? `${savings.total.toFixed(0)} pts`
          : "—",
    sub:
      savings.runs > 0
        ? `${savings.runs} accepted LNS run${savings.runs === 1 ? "" : "s"} · ${savings.total.toFixed(1)} cost saved`
        : "run ⚡ LNS to quantify the engine's value",
  });

  const toneCls: Record<string, string> = {
    ok: "border-emerald-500/30",
    warn: "border-amber-500/40",
    danger: "border-rose-500/40",
    info: "border-sky-500/30",
    accent: "border-teal-500/40",
  };
  const valueCls: Record<string, string> = {
    ok: "text-emerald-300",
    warn: "text-amber-300",
    danger: "text-rose-300",
    info: "text-sky-300",
    accent: "text-teal-300",
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 mt-4">
      {cards.map((c) => (
        <button
          key={c.key}
          onClick={c.onClick}
          disabled={!c.onClick}
          className={`rounded-xl border bg-slate-900/70 px-3.5 py-2.5 text-left transition-colors ${
            toneCls[c.tone]
          } ${c.onClick ? "hover:bg-slate-800 cursor-pointer" : "cursor-default"}`}
        >
          <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">{c.label}</div>
          <div className={`tnum text-xl font-bold leading-tight ${valueCls[c.tone]}`}>{c.value}</div>
          <div className="text-[10px] text-slate-500 truncate">{c.sub}</div>
        </button>
      ))}
    </div>
  );
}