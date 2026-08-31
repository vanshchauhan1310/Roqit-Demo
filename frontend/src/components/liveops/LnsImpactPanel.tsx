import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, Marker, Polyline, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import { HYDERABAD_CENTER, HYDERABAD_BOUNDS } from "@/utils/serviceArea";
import { colorForRouteId } from "@/utils/routeColors";
import type { LnsRun, LnsPlanSnapshot, MovedTrip } from "@/types/lns";

type ViewMode = "before" | "after" | "replay";

/** Pickup positions per trip: {tripId: {routeId, latlng}} */
function pickupIndex(plan: LnsPlanSnapshot | null): Map<string, { routeId: string; latlng: [number, number] | null }> {
  const idx = new Map<string, { routeId: string; latlng: [number, number] | null }>();
  if (!plan) return idx;
  for (const [routeId, r] of Object.entries(plan)) {
    for (const s of r.stops ?? []) {
      if (s.stop_type === "pickup" && s.trip_id) {
        idx.set(s.trip_id, {
          routeId,
          latlng: s.latitude != null && s.longitude != null ? [s.latitude, s.longitude] : null,
        });
      }
    }
  }
  return idx;
}

/** Trips whose pickup ended up on a different route after the run. */
function computeMovedTrips(run: LnsRun): MovedTrip[] {
  const before = pickupIndex(run.routes_before);
  const after = pickupIndex(run.routes_after);
  const moved: MovedTrip[] = [];
  for (const [tripId, b] of before) {
    const a = after.get(tripId);
    if (!a) continue;
    if (a.routeId === b.routeId) continue;
    if (b.latlng && a.latlng) moved.push({ tripId, from: b.latlng, to: a.latlng });
  }
  return moved;
}

function FitAll({ positions, depKey }: { positions: [number, number][]; depKey: string }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length === 0) {
      map.setView(HYDERABAD_CENTER, 11);
    } else if (positions.length === 1) {
      map.setView(positions[0], 12);
    } else {
      map.fitBounds(L.latLngBounds(positions), { padding: [30, 30], maxZoom: 13 });
    }
  }, [map, depKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function serviceBoundsRect(map: L.Map) {
  return L.rectangle(
    L.latLngBounds(
      [HYDERABAD_BOUNDS.minLat, HYDERABAD_BOUNDS.minLon],
      [HYDERABAD_BOUNDS.maxLat, HYDERABAD_BOUNDS.maxLon],
    ),
    { color: "#475569", weight: 1, dashArray: "6 6", fill: false },
  ).addTo(map);
}

/** Service boundary drawn via react-leaflet lifecycle. */
function BoundsLayer() {
  const map = useMap();
  useEffect(() => {
    const rect = serviceBoundsRect(map);
    return () => {
      rect.remove();
    };
  }, [map]);
  return null;
}

const GRAY = "#64748b";

function planPositions(plan: LnsPlanSnapshot | null): [number, number][] {
  const pts: [number, number][] = [];
  if (!plan) return pts;
  for (const r of Object.values(plan)) {
    for (const s of r.stops ?? []) {
      if (s.latitude != null && s.longitude != null) pts.push([s.latitude, s.longitude]);
    }
  }
  return pts;
}

function ImpactMap({ run, mode, replayNonce }: { run: LnsRun; mode: ViewMode; replayNonce: number }) {
  const before = run.routes_before;
  const after = run.routes_after;
  const moved = useMemo(() => (mode === "replay" ? computeMovedTrips(run) : []), [run, mode]);
  const allPositions = useMemo(
    () => [...planPositions(before), ...planPositions(after)],
    [before, after],
  );
  // Key on nonce so replay re-mounts layers and CSS animations restart.
  const layerKey = `${run.run_id}-${mode}-${replayNonce}`;
  const afterEntries = useMemo(() => Object.entries(after ?? {}), [after]);
  const beforeEntries = useMemo(() => Object.entries(before ?? {}), [before]);

  return (
    <div className="relative rounded-lg overflow-hidden border border-slate-700/60 dark-map">
      <MapContainer
        center={HYDERABAD_CENTER}
        zoom={11}
        minZoom={9}
        maxBounds={L.latLngBounds(
          [HYDERABAD_BOUNDS.minLat - 0.5, HYDERABAD_BOUNDS.minLon - 0.5],
          [HYDERABAD_BOUNDS.maxLat + 0.5, HYDERABAD_BOUNDS.maxLon + 0.5],
        )}
        style={{ height: 300, width: "100%" }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <BoundsLayer />
        <FitAll positions={allPositions} depKey={layerKey} />
        <PlanLayers
          layerKey={layerKey}
          mode={mode}
          beforeEntries={beforeEntries}
          afterEntries={afterEntries}
        />
        {mode === "replay" &&
          moved.map((m, i) => (
            <Polyline
              key={`f-${layerKey}-${m.tripId}`}
              positions={[m.from, m.to]}
              pathOptions={{
                color: "#fbbf24",
                weight: 2.5,
                opacity: 0.9,
                dashArray: "5 9",
                className: `lns-flight lns-f-${Math.min(i, 11)}`,
              }}
            >
              <Tooltip direction="top" offset={[0, -8]}>{`moved · ${m.tripId}`}</Tooltip>
            </Polyline>
          ))}
      </MapContainer>

      <div className="absolute top-2 left-2 z-[1000] rounded-md px-2.5 py-1 text-[10px] font-bold tracking-[0.14em] uppercase bg-slate-950/85 border border-slate-700 text-slate-200">
        {mode === "before" && "Plan before LNS"}
        {mode === "after" && "Plan after LNS"}
        {mode === "replay" && `Replay — ${moved.length} trip${moved.length === 1 ? "" : "s"} moved`}
      </div>
    </div>
  );
}

function PlanLayers({
  layerKey,
  mode,
  beforeEntries,
  afterEntries,
}: {
  layerKey: string;
  mode: ViewMode;
  beforeEntries: [string, LnsPlanSnapshot[string]][];
  afterEntries: [string, LnsPlanSnapshot[string]][];
}) {
  const showBeforeLayer = mode === "before" || mode === "replay";
  const showAfterLayer = mode === "after" || mode === "replay";
  return (
    <>
      {showBeforeLayer &&
        beforeEntries.map(([routeId, r]) => {
          const pts = (r.stops ?? [])
            .filter((s) => s.latitude != null && s.longitude != null)
            .map((s) => [s.latitude as number, s.longitude as number] as [number, number]);
          if (pts.length < 2) return null;
          return (
            <Polyline
              key={`b-${layerKey}-${routeId}`}
              positions={pts}
              pathOptions={{
                color: GRAY,
                weight: 2.5,
                opacity: mode === "replay" ? 0.18 : 0.75,
                dashArray: "7 7",
              }}
            />
          );
        })}
      {showBeforeLayer &&
        beforeEntries.map(([routeId, r]) =>
          (r.stops ?? []).map((s) =>
            s.latitude == null || s.longitude == null ? null : (
              <CircleMarker
                key={`bs-${layerKey}-${routeId}-${s.stop_id}`}
                center={[s.latitude, s.longitude]}
                radius={4}
                pathOptions={{ color: GRAY, fillOpacity: mode === "replay" ? 0.15 : 0.6, weight: 1 }}
              >
                {mode === "before" && (
                  <Tooltip direction="top" offset={[0, -8]}>
                    {`#${s.sequence} ${s.stop_type}${s.trip_id ? ` — ${s.trip_id}` : ""}`}
                  </Tooltip>
                )}
              </CircleMarker>
            ),
          ),
        )}

      {showAfterLayer &&
        afterEntries.map(([routeId, r], i) => {
          const pts = (r.stops ?? [])
            .filter((s) => s.latitude != null && s.longitude != null)
            .map((s) => [s.latitude as number, s.longitude as number] as [number, number]);
          if (pts.length < 2) return null;
          return (
            <Polyline
              key={`a-${layerKey}-${routeId}`}
              positions={pts}
              pathOptions={{
                color: colorForRouteId(routeId),
                weight: 3.5,
                opacity: 0.9,
                className: mode === "replay" ? `lns-draw lns-d-${Math.min(i, 15)}` : undefined,
              }}
            />
          );
        })}
      {mode === "after" &&
        afterEntries.map(([routeId, r]) =>
          (r.stops ?? []).map((s, si) =>
            s.latitude == null || s.longitude == null ? null : (
              <Marker
                key={`as-${layerKey}-${routeId}-${s.stop_id}`}
                position={[s.latitude, s.longitude]}
                icon={L.divIcon({
                  className: "",
                  html: `<div style="background:${colorForRouteId(routeId)};color:#fff;border:2px solid #fff;border-radius:9999px;width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;box-shadow:0 1px 2px rgba(0,0,0,.4)">${s.sequence ?? si + 1}</div>`,
                  iconSize: [20, 20],
                  iconAnchor: [10, 10],
                })}
              >
                <Tooltip direction="top" offset={[0, -10]}>
                  {`#${s.sequence ?? si + 1} ${s.stop_type}${s.trip_id ? ` — ${s.trip_id}` : ""}`}
                </Tooltip>
              </Marker>
            ),
          ),
        )}
    </>
  );
}

function MetricCell({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
      <div className="text-[9px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className={`tnum text-sm font-semibold ${accent ?? "text-slate-100"}`}>{value}</div>
    </div>
  );
}

interface RouteDiffRow {
  routeId: string;
  name: string;
  vehicleId: string | null;
  stopsBefore: number;
  stopsAfter: number;
  state: "changed" | "unchanged" | "new" | "removed";
}

function buildDiff(run: LnsRun): RouteDiffRow[] {
  const before = run.routes_before ?? {};
  const after = run.routes_after ?? {};
  const ids = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return ids.map((routeId) => {
    const b = before[routeId];
    const a = after[routeId];
    const stopsBefore = b?.stops?.length ?? 0;
    const stopsAfter = a?.stops?.length ?? 0;
    const state: RouteDiffRow["state"] = !b
      ? "new"
      : !a
        ? "removed"
        : JSON.stringify(b.stops) !== JSON.stringify(a.stops)
          ? "changed"
          : "unchanged";
    return {
      routeId,
      name: (a ?? b)?.name ?? routeId.slice(0, 8),
      vehicleId: (a ?? b)?.vehicle_id ?? null,
      stopsBefore,
      stopsAfter,
      state,
    };
  });
}

const STATE_BADGE: Record<RouteDiffRow["state"], { label: string; cls: string }> = {
  changed: { label: "rescheduled", cls: "bg-teal-500/15 text-teal-300 border-teal-500/40" },
  unchanged: { label: "unchanged", cls: "bg-slate-500/10 text-slate-400 border-slate-600/40" },
  new: { label: "opened", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40" },
  removed: { label: "closed", cls: "bg-rose-500/15 text-rose-300 border-rose-500/40" },
};

export function LnsImpactPanel({
  open,
  runs,
  initialRunId,
  onClose,
}: {
  open: boolean;
  runs: LnsRun[];
  initialRunId?: string | null;
  onClose: () => void;
}) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId ?? null);
  const [mode, setMode] = useState<ViewMode>("replay");
  const [replayNonce, setReplayNonce] = useState(0);

  // Follow the initial run (auto-open after a trigger) and reset to replay.
  useEffect(() => {
    if (open) {
      setSelectedRunId(initialRunId ?? runs[0]?.run_id ?? null);
      setMode("replay");
      setReplayNonce((n) => n + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialRunId]);

  const run = runs.find((r) => r.run_id === selectedRunId) ?? runs[0] ?? null;
  const accepted = run?.status === "completed";
  const movedCount = useMemo(() => (run ? computeMovedTrips(run).length : 0), [run]);
  const diff = useMemo(() => (run ? buildDiff(run) : []), [run]);

  const selectRun = (id: string) => {
    setSelectedRunId(id);
    setMode("replay");
    setReplayNonce((n) => n + 1);
  };

  const replay = () => {
    setMode("replay");
    setReplayNonce((n) => n + 1);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[1200]">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="absolute top-0 right-0 z-[1300] h-full w-[600px] max-w-[95vw] bg-slate-950 border-l border-slate-700 shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800">
          <div>
            <h2 className="text-sm font-bold tracking-tight text-slate-100">
              LNS IMPACT <span className="text-teal-400">· BEFORE ⇄ AFTER</span>
            </h2>
            <p className="text-[10px] text-slate-500 mt-0.5">
              Large Neighborhood Search — destroy &amp; repair result with full plan comparison
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-500"
          >
            Close ✕
          </button>
        </div>

        {/* Run history chips */}
        <div className="flex gap-1.5 px-5 py-2.5 border-b border-slate-800 overflow-x-auto ops-scroll">
          {runs.length === 0 && (
            <span className="text-xs text-slate-500 py-1">
              No LNS runs recorded yet — trigger one with ⚡ LNS.
            </span>
          )}
          {runs.map((r) => {
            const ok = r.status === "completed";
            return (
              <button
                key={r.run_id}
                onClick={() => selectRun(r.run_id)}
                className={`lns-chip-enter shrink-0 rounded-md border px-2.5 py-1 text-[10px] tnum ${
                  r.run_id === run?.run_id
                    ? "border-teal-500/70 bg-teal-500/10 text-teal-200"
                    : "border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-500"
                }`}
              >
                {new Date(r.created_at ?? Date.now()).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
                {" · "}
                {r.improvement_pct != null
                  ? `${r.improvement_pct > 0 ? "−" : "+"}${Math.abs(r.improvement_pct).toFixed(1)}%`
                  : "—"}
                {ok ? " ✔" : " ↩"}
              </button>
            );
          })}
        </div>

        {run ? (
          <PanelBody
            run={run}
            accepted={accepted}
            movedCount={movedCount}
            diff={diff}
            mode={mode}
            replayNonce={replayNonce}
            onReplay={replay}
            setMode={setMode}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-slate-500">
            Select an LNS run to see its before/after impact.
          </div>
        )}
      </div>
    </div>
  );
}

function PanelBody({
  run,
  accepted,
  movedCount,
  diff,
  mode,
  replayNonce,
  onReplay,
  setMode,
}: {
  run: LnsRun;
  accepted: boolean;
  movedCount: number;
  diff: RouteDiffRow[];
  mode: ViewMode;
  replayNonce: number;
  onReplay: () => void;
  setMode: (m: ViewMode) => void;
}) {
  return (
    <div className="flex-1 overflow-y-auto ops-scroll px-5 py-4 space-y-4">
      {/* Verdict */}
      <div
        className={`rounded-lg border px-4 py-3 ${
          accepted ? "border-teal-500/40 bg-teal-500/5" : "border-amber-500/40 bg-amber-500/5"
        }`}
      >
        <div className="flex items-center justify-between">
          <span
            className={`text-xs font-bold tracking-[0.12em] uppercase ${
              accepted ? "text-teal-300" : "text-amber-300"
            }`}
          >
            {accepted ? "✔ Plan improved — accepted" : "↩ No improvement — rolled back"}
          </span>
          {run.improvement_pct != null && (
            <span
              className={`tnum text-xl font-bold ${
                run.improvement_pct > 0 ? "text-teal-300" : "text-slate-400"
              }`}
            >
              {run.improvement_pct > 0 ? "−" : "+"}
              {Math.abs(run.improvement_pct).toFixed(1)}%
            </span>
          )}
        </div>
        <div className="text-[10px] text-slate-500 mt-1">
          {run.run_type === "TRIGGERED_LNS" ? "manual trigger" : "automatic periodic run"} · destroy:{" "}
          {run.destroy_strategy ?? "—"} · repair: {run.repair_strategy ?? "—"} · {run.execution_time_ms} ms ·{" "}
          {run.created_at ? new Date(run.created_at).toLocaleTimeString() : "—"}
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-2">
        <MetricCell label="Cost before" value={run.old_cost != null ? run.old_cost.toFixed(1) : "—"} />
        <MetricCell
          label="Cost after"
          value={run.new_cost != null ? run.new_cost.toFixed(1) : "—"}
          accent={accepted ? "text-teal-300" : undefined}
        />
        <MetricCell label="Routes touched" value={String(run.routes_affected)} />
        <MetricCell label="Trips moved" value={String(movedCount)} />
      </div>

      {/* Map with mode toggle */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex rounded-md overflow-hidden border border-slate-700">
            {(["before", "after", "replay"] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => (m === "replay" ? onReplay() : setMode(m))}
                className={`px-3 py-1 text-[10px] font-bold tracking-[0.12em] uppercase transition-colors ${
                  mode === m
                    ? "bg-teal-500/20 text-teal-200"
                    : "bg-slate-900 text-slate-400 hover:text-slate-200"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
          <span className="hidden lg:inline text-[10px] text-slate-500">
            gray dashed = old · colored = new · amber = trip moved
          </span>
        </div>
        <ImpactMap run={run} mode={mode} replayNonce={replayNonce} />
      </div>

      {/* Per-route diff */}
      <div>
        <h3 className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500 mb-2">
          Route-by-route comparison
        </h3>
        <div className="rounded-lg border border-slate-800 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-900 text-slate-500 text-[9px] uppercase tracking-[0.12em]">
                <th className="text-left px-3 py-2 font-medium">Route</th>
                <th className="text-left px-3 py-2 font-medium">Vehicle</th>
                <th className="text-center px-3 py-2 font-medium">Before</th>
                <th className="text-center px-3 py-2 font-medium">After</th>
                <th className="text-right px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {diff.map((row) => (
                <tr key={row.routeId} className="bg-slate-950/60">
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ background: colorForRouteId(row.routeId) }}
                      />
                      <span className="text-slate-200">{row.name ?? row.routeId.slice(0, 8)}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2 tnum text-slate-400">{row.vehicleId ?? "—"}</td>
                  <td className="px-3 py-2 text-center tnum text-slate-400">{row.stopsBefore}</td>
                  <td className="px-3 py-2 text-center tnum text-slate-200">
                    {row.stopsAfter}
                    {row.stopsAfter !== row.stopsBefore && (
                      <span className={row.stopsAfter > row.stopsBefore ? "text-teal-400" : "text-rose-400"}>
                        {" "}
                        ({row.stopsAfter > row.stopsBefore ? "+" : ""}
                        {row.stopsAfter - row.stopsBefore})
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${
                        STATE_BADGE[row.state].cls
                      }`}
                    >
                      {STATE_BADGE[row.state].label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}