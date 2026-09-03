import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";

export interface KpiPoint {
  t: number;
  queue: number;
  trips: number;
  routes: number;
  utilization: number;
}

function Spark({
  data,
  color,
  dataKey,
}: {
  data: KpiPoint[];
  color: string;
  dataKey: keyof KpiPoint;
}) {
  return (
    <ResponsiveContainer width="100%" height={34}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={`g-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.45} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <YAxis hide domain={[0, (max: number) => Math.max(4, max * 1.3)]} />
        <Area
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#g-${dataKey})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function Tile({
  label,
  value,
  sub,
  color,
  data,
  dataKey,
  onClick,
  tooltip,
}: {
  label: string;
  value: string | number;
  sub: string;
  color: string;
  data: KpiPoint[];
  dataKey: keyof KpiPoint;
  onClick?: () => void;
  tooltip?: string;
}) {
  return (
    <div
      onClick={onClick}
      title={tooltip}
      className={`relative group rounded-xl border border-slate-800 bg-slate-900/70 px-3.5 py-3${
        onClick
          ? " cursor-pointer hover:border-slate-600 transition-colors"
          : ""
      }`}
    >
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
          {label}
        </span>
        <span className="text-[10px] text-slate-500">{sub}</span>
      </div>
      <div className="text-2xl font-semibold text-slate-100 tnum leading-tight">
        {value}
      </div>
      <Spark data={data} color={color} dataKey={dataKey} />
      {onClick && (
        <span className="absolute top-2.5 right-2.5 text-[9px] text-slate-600 group-hover:text-slate-400">
          view ›
        </span>
      )}
      {tooltip && (
        <div className="pointer-events-none absolute left-1/2 bottom-full z-30 mb-1.5 w-56 -translate-x-1/2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-[10px] leading-snug text-slate-300 opacity-0 shadow-xl transition-opacity group-hover:opacity-100">
          {tooltip}
        </div>
      )}
    </div>
  );
}

function CountdownRing({ seconds, total }: { seconds: number; total: number }) {
  const r = 15;
  const c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, seconds / total));
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" className="-rotate-90">
      <circle
        cx="20"
        cy="20"
        r={r}
        fill="none"
        stroke="#1e293b"
        strokeWidth="3.5"
      />
      <circle
        cx="20"
        cy="20"
        r={r}
        fill="none"
        stroke="#5eead4"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - frac)}
        style={{ transition: "stroke-dashoffset 0.9s linear" }}
      />
      <text
        x="20"
        y="24"
        textAnchor="middle"
        fontSize="11"
        fill="#e2e8f0"
        className="tnum"
        transform="rotate(90 20 20)"
      >
        {seconds}
      </text>
    </svg>
  );
}

/** KPI band with sparklines + the auto-feed countdown ring. */
export function KpiTiles({
  data,
  queue,
  trips,
  routes,
  utilization,
  avgLatency,
  feedSecondsLeft,
  feedIntervalSec,
  feedEnabled,
  onToggleFeed,
  onGenerateNow,
  onOptimize,
  optimizing,
  onOpenQueueDetail,
  onOpenTripsDetail,
  onOpenRoutesDetail,
}: {
  data: KpiPoint[];
  queue: number;
  trips: number;
  routes: number;
  utilization: number;
  avgLatency: number | null;
  feedSecondsLeft: number;
  feedIntervalSec: number;
  feedEnabled: boolean;
  onToggleFeed: () => void;
  onGenerateNow: () => void;
  onOptimize: () => void;
  optimizing: boolean;
  onOpenQueueDetail: () => void;
  onOpenTripsDetail: () => void;
  onOpenRoutesDetail: () => void;
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      <Tile
        label="Queue depth"
        value={queue}
        sub="unassigned"
        color="#fbbf24"
        data={data}
        dataKey="queue"
        onClick={onOpenQueueDetail}
      />
      <Tile
        label="Trips today"
        value={trips}
        sub={queue > 0 ? `${queue} unassigned` : "all assigned"}
        color="#38bdf8"
        data={data}
        dataKey="trips"
        onClick={onOpenTripsDetail}
        tooltip={`Total trips in the system. "Unassigned" = trips that have not yet been routed to a vehicle/driver — they sit in the assignment queue until the engine's greedy best-insertion solver finds a feasible route (respecting capacity, distance, time-window, and driver HOS limits). When the fleet has duty hours available, the queue drains toward zero.`}
      />
      <Tile
        label="Active routes"
        value={routes}
        sub="fleet"
        color="#34d399"
        data={data}
        dataKey="routes"
        onClick={onOpenRoutesDetail}
      />
      <Tile
        label="Fleet utilization"
        value={`${utilization}%`}
        sub="capacity"
        color="#a78bfa"
        data={data}
        dataKey="utilization"
        tooltip="Share of total fleet payload capacity currently booked by assigned trips: sum(used_capacity_kg) / sum(capacity_kg) across all routes. Low % means lots of free capacity; >90% means routes are near their load limit."
      />
      <Tile
        label="Avg assignment"
        value={avgLatency != null ? `${avgLatency}s` : "—"}
        sub="queue latency"
        color="#f472b6"
        data={data}
        dataKey="trips"
        tooltip="Average queue latency: the mean time between a trip being received by the engine and its assignment to a route. This includes the greedy best-insertion solver scoring all candidate routes (capacity, distance, time-window feasibility, driver HOS limits) and selecting the minimum-cost insertion. A rising number means the engine is falling behind incoming demand; a low/zero number means it is keeping up."
      />

      {/* Feed control tile */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3.5 py-3">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
            Auto feed
          </span>
          <CountdownRing
            seconds={feedEnabled ? feedSecondsLeft : 0}
            total={feedIntervalSec}
          />
        </div>
        <div className="flex items-center gap-1.5 mt-1">
          <button
            onClick={onToggleFeed}
            className={`rounded-md px-2.5 py-1 text-[11px] font-semibold ${
              feedEnabled
                ? "bg-slate-800 text-slate-300 hover:bg-slate-700"
                : "bg-teal-500 text-slate-950 hover:bg-teal-400"
            }`}
          >
            {feedEnabled ? "Pause" : "Start"}
          </button>
          <button
            onClick={onGenerateNow}
            className="rounded-md px-2.5 py-1 text-[11px] font-medium border border-slate-700 text-slate-300 hover:bg-slate-800"
          >
            + Trip
          </button>
          <button
            onClick={onOptimize}
            disabled={optimizing}
            className="rounded-md px-2.5 py-1 text-[11px] font-medium border border-fuchsia-500/40 text-fuchsia-300 hover:bg-fuchsia-500/10 disabled:opacity-40"
          >
            {optimizing ? "LNS…" : "⚡ LNS"}
          </button>
        </div>
      </div>
    </div>
  );
}
