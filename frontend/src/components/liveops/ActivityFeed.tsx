import type { OpsEvent } from "@/hooks/useOpsEvents";

const TYPE_STYLE: Record<OpsEvent["type"], { icon: string; dot: string; label: string }> = {
  trip_received: { icon: "↓", dot: "bg-amber-400", label: "text-amber-300" },
  trip_assigned: { icon: "✓", dot: "bg-teal-400", label: "text-teal-300" },
  route_created: { icon: "+", dot: "bg-sky-400", label: "text-sky-300" },
  stops_planned: { icon: "◆", dot: "bg-violet-400", label: "text-violet-300" },
  lns_triggered: { icon: "⚡", dot: "bg-fuchsia-400", label: "text-fuchsia-300" },
};

function ago(ts: number): string {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m${s % 60}s`;
}

/** Mission-control event stream — every engine decision, live. */
export function ActivityFeed({
  events,
  onOpenTrip,
  onOpenRoute,
}: {
  events: OpsEvent[];
  onOpenTrip: (id: string) => void;
  onOpenRoute: (id: string) => void;
}) {
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Live Engine Feed
        </h2>
        <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-60 animate-ping" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-teal-400" />
          </span>
          streaming
        </span>
      </div>
      <div className="flex-1 overflow-y-auto ops-scroll divide-y divide-slate-800/70">
        {events.length === 0 && (
          <p className="px-4 py-8 text-xs text-slate-500 text-center">
            Waiting for engine activity…
          </p>
        )}
        {events.map((e) => {
          const st = TYPE_STYLE[e.type];
          const clickable = e.tripId ?? e.routeId;
          return (
            <button
              key={e.id}
              onClick={() => (e.tripId ? onOpenTrip(e.tripId) : e.routeId ? onOpenRoute(e.routeId) : undefined)}
              disabled={!clickable}
              className={`w-full text-left px-4 py-2.5 flex gap-3 ${clickable ? "hover:bg-slate-800/50" : ""} feed-row-enter`}
            >
              <span className={`mt-1 w-1 h-8 rounded-full shrink-0 ${st.dot}`} />
              <span className="min-w-0 flex-1">
                <span className={`block text-xs font-semibold tracking-wide ${st.label}`}>{e.title}</span>
                <span className="block text-[11px] text-slate-400 leading-snug">{e.detail}</span>
              </span>
              <span className="text-[10px] text-slate-600 tnum shrink-0">{ago(e.ts)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}