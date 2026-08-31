import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";

export interface KpiPoint {
  t: number;
  queue: number;
  trips: number;
  routes: number;
  utilization: number;
}

function Spark({ data, color, dataKey }: { data: KpiPoint[]; color: string; dataKey: keyof KpiPoint }) {
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
}: {
  label: string;
  value: string | number;
  sub: string;
  color: string;
  data: KpiPoint[];
  dataKey: keyof KpiPoint;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3.5 py-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</span>
        <span className="text-[10px] text-slate-500">{sub}</span>
      </div>
      <div className="text-2xl font-semibold text-slate-100 tnum leading-tight">{value}</div>
      <Spark data={data} color={color} dataKey={dataKey} />
    </div>
  );
}

function CountdownRing({ seconds, total }: { seconds: number; total: number }) {
  const r = 15;
  const c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, seconds / total));
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" className="-rotate-90">
      <circle cx="20" cy="20" r={r} fill="none" stroke="#1e293b" strokeWidth="3.5" />
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
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      <Tile label="Queue depth" value={queue} sub="unassigned" color="#fbbf24" data={data} dataKey="queue" />
      <Tile label="Trips today" value={trips} sub="total" color="#38bdf8" data={data} dataKey="trips" />
      <Tile label="Active routes" value={routes} sub="fleet" color="#34d399" data={data} dataKey="routes" />
      <Tile
        label="Fleet utilization"
        value={`${utilization}%`}
        sub="capacity"
        color="#a78bfa"
        data={data}
        dataKey="utilization"
      />
      <Tile
        label="Avg assignment"
        value={avgLatency != null ? `${avgLatency}s` : "—"}
        sub="queue latency"
        color="#f472b6"
        data={data}
        dataKey="trips"
      />

      {/* Feed control tile */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3.5 py-3">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">Auto feed</span>
          <CountdownRing seconds={feedEnabled ? feedSecondsLeft : 0} total={feedIntervalSec} />
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