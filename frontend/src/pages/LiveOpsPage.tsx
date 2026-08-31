import { useEffect, useMemo, useRef, useState } from "react";
import { useIncomingTrips, useAllTripsLive, useRoutesLive } from "@/hooks/useLiveOps";
import { useTripSimulator } from "@/hooks/useTripSimulator";
import { useOpsEvents } from "@/hooks/useOpsEvents";
import { useLnsHistory } from "@/hooks/useLnsHistory";
import { useFleet } from "@/hooks/useFleet";
import { LiveOpsMap } from "@/components/liveops/LiveOpsMap";
import { ActivityFeed } from "@/components/liveops/ActivityFeed";
import { KpiTiles, type KpiPoint } from "@/components/liveops/KpiTiles";
import { PlanStrip } from "@/components/liveops/PlanStrip";
import { DetailDrawer, type Selection } from "@/components/liveops/DetailDrawer";
import { LnsImpactPanel } from "@/components/liveops/LnsImpactPanel";
import { AlertStrip } from "@/components/liveops/AlertStrip";
import { OpsIntelPanel } from "@/components/liveops/OpsIntelPanel";
import { triggerLns } from "@/api/routes";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

export function LiveOpsPage() {
  const { data: incoming = [], isLoading: loadingIncoming } = useIncomingTrips(3000);
  const { data: allTrips = [] } = useAllTripsLive(5000);
  const { data: routes = [] } = useRoutesLive(5000);
  const sim = useTripSimulator();
  const clock = useClock();
  const { events, flights, latenciesSec, pushEvent } = useOpsEvents(incoming, allTrips, routes);

  const [selection, setSelection] = useState<Selection>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const lns = useLnsHistory();
  const fleet = useFleet();
  const [impactOpen, setImpactOpen] = useState(false);
  const [impactRunId, setImpactRunId] = useState<string | null>(null);
  const [intelOpen, setIntelOpen] = useState(false);

  const openTrip = (id: string) => setSelection({ type: "trip", id });
  const openRoute = (id: string) => {
    setSelectedRouteId(id);
    setSelection({ type: "route", id });
  };
  const handleMapRouteSelect = (id: string | null) => {
    setSelectedRouteId(id);
    if (id) setSelection({ type: "route", id });
  };

  const utilization = useMemo(() => {
    const cap = routes.reduce((a, r) => a + (r.capacity_kg ?? 0), 0);
    const used = routes.reduce((a, r) => a + (r.used_capacity_kg ?? 0), 0);
    return cap > 0 ? Math.round((used / cap) * 100) : 0;
  }, [routes]);
  const avgLatency = latenciesSec.length
    ? Math.round((latenciesSec.reduce((a, b) => a + b, 0) / latenciesSec.length) * 10) / 10
    : null;

  // Rolling KPI history for the sparklines (one point per poll cycle).
  const [kpiData, setKpiData] = useState<KpiPoint[]>([]);
  const lastKpiRef = useRef(0);
  useEffect(() => {
    const now = Date.now();
    if (now - lastKpiRef.current < 4000) return;
    lastKpiRef.current = now;
    setKpiData((d) => [
      ...d.slice(-39),
      { t: now, queue: incoming.length, trips: allTrips.length, routes: routes.length, utilization },
    ]);
  }, [incoming.length, allTrips.length, routes.length, utilization]);

  const handleOptimize = async () => {
    setOptimizing(true);
    pushEvent({
      type: "lns_triggered",
      title: "LNS OPTIMIZATION · triggered",
      detail: "Large Neighborhood Search dispatched — destroy & repair across all routes",
    });
    const knownRunId = lns.latestRunId;
    try {
      await triggerLns();
    } catch {
      /* queue may reject if busy — the feed will show the result either way */
    }
    setTimeout(() => setOptimizing(false), 6000);

    // The optimizer runs asynchronously on the backend worker; wait for the
    // new audit row, then open the Before/After impact panel automatically.
    const run = await lns.waitForNewRun(knownRunId);
    if (run) {
      setImpactRunId(run.run_id);
      setImpactOpen(true);
      const pct = run.improvement_pct;
      pushEvent({
        type: "lns_triggered",
        title: `LNS RUN · ${run.status === "completed" ? "accepted" : "rolled back"}`,
        detail:
          (pct != null
            ? `plan cost ${run.old_cost?.toFixed(1)} → ${run.new_cost?.toFixed(1)} (−${Math.abs(pct).toFixed(1)}%)`
            : "comparison ready") +
          ` · ${run.routes_affected} route(s) touched — click to compare before/after`,
      });
    }
  };

  const openLnsHistory = () => {
    setImpactRunId(null); // show latest
    setImpactOpen(true);
  };

  return (
    <div className="rounded-2xl bg-slate-950 text-slate-100 -m-6 p-5 min-h-[calc(100vh-3rem)]">
      {/* Command bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <span className="relative flex h-3 w-3">
            <span className="absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-60 animate-ping" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-teal-400" />
          </span>
          <h1 className="text-lg font-bold tracking-tight">
            ROQIT <span className="text-teal-400">LIVE OPS</span>
          </h1>
          <span className="rounded-full border border-slate-700 px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-400">
            Hyderabad service area
          </span>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-slate-400">
          {loadingIncoming && <span className="text-slate-500">syncing…</span>}
          <button
            onClick={openLnsHistory}
            className="rounded-md border border-slate-700 px-2.5 py-1 text-[10px] font-bold tracking-[0.12em] uppercase text-slate-300 hover:border-teal-500/60 hover:text-teal-300 transition-colors"
            title="LNS run history — before/after plan comparison"
          >
            ⇄ LNS history
          </button>
          <button
            onClick={() => setIntelOpen(true)}
            className="rounded-md border border-slate-700 px-2.5 py-1 text-[10px] font-bold tracking-[0.12em] uppercase text-slate-300 hover:border-sky-500/60 hover:text-sky-300 transition-colors"
            title="Fleet utilization, costs, driver scorecards, savings ROI, SLA, activity"
          >
            📊 Intel
          </button>
          <span className="tnum text-slate-200 text-sm">{clock.toLocaleTimeString()}</span>
          <span className="hidden md:inline">greedy insertion · LNS · auto-dispatch</span>
        </div>
      </div>

      <KpiTiles
        data={kpiData}
        queue={incoming.length}
        trips={allTrips.length}
        routes={routes.length}
        utilization={utilization}
        avgLatency={avgLatency}
        feedSecondsLeft={Math.ceil(sim.nextTripInMs / 1000)}
        feedIntervalSec={Math.round(sim.intervalMs / 1000)}
        feedEnabled={sim.enabled}
        onToggleFeed={() => sim.setEnabled(!sim.enabled)}
        onGenerateNow={() => void sim.generateNow()}
        onOptimize={() => void handleOptimize()}
        optimizing={optimizing}
      />

      {/* Operator alerts + stakeholder savings — click a card to jump in */}
      <AlertStrip
        incoming={incoming}
        allTrips={allTrips}
        routes={routes}
        lnsRuns={lns.runs}
        onOpenTrip={openTrip}
        onOpenRoute={openRoute}
      />

      {/* Mission grid: event rail | map + plan builder */}
      <div className="grid xl:grid-cols-[330px_1fr] gap-4 mt-4 items-start">
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 h-[640px] flex flex-col overflow-hidden">
          <ActivityFeed events={events} onOpenTrip={openTrip} onOpenRoute={openRoute} />
        </div>

        <div className="space-y-4 min-w-0">
          <LiveOpsMap
            incomingTrips={incoming}
            routes={routes}
            selectedRouteId={selectedRouteId}
            onSelectRoute={handleMapRouteSelect}
            onSelectTrip={openTrip}
            flights={flights}
          />
          <PlanStrip routes={routes} onOpenRoute={openRoute} selectedRouteId={selectedRouteId} />
        </div>
      </div>

      <DetailDrawer selection={selection} onSelect={setSelection} onClose={() => setSelection(null)} />
      <LnsImpactPanel
        open={impactOpen}
        runs={lns.runs}
        initialRunId={impactRunId}
        onClose={() => setImpactOpen(false)}
      />
      <OpsIntelPanel
        open={intelOpen}
        routes={routes}
        trips={allTrips}
        vehicles={fleet.vehicles}
        drivers={fleet.drivers}
        lnsRuns={lns.runs}
        latenciesSec={latenciesSec}
        onClose={() => setIntelOpen(false)}
        onOpenRoute={openRoute}
      />
    </div>
  );
}