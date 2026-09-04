import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, Marker, Polyline, CircleMarker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import { HYDERABAD_CENTER, HYDERABAD_BOUNDS } from "@/utils/serviceArea";
import { colorForRouteId } from "@/utils/routeColors";
import type { LnsRun, LnsPlanSnapshot, LnsSnapshotStop, MovedTrip } from "@/types/lns";

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

interface RoutePlanDiffRow {
  routeId: string;
  name: string;
  vehicleId: string | null;
  beforeStops: LnsSnapshotStop[];
  afterStops: LnsSnapshotStop[];
  added: LnsSnapshotStop[]; // present in after, not in before
  removed: LnsSnapshotStop[]; // present in before, not in after
  movedIn: MovedTrip[]; // trips that joined this route
  movedOut: MovedTrip[]; // trips that left this route
  state: "changed" | "unchanged" | "new" | "removed";
}

function stopKey(s: LnsSnapshotStop): string {
  return `${s.trip_id ?? ""}:${s.stop_type}`;
}

/** Rich per-route diff: which stops/sequences changed and which trips moved. */
function buildDetailedDiff(run: LnsRun): RoutePlanDiffRow[] {
  const before = run.routes_before ?? {};
  const after = run.routes_after ?? {};
  const moved = computeMovedTrips(run);

  // tripId -> routeId for pickup stops so we can attribute moved trips.
  const beforeTripRoute = new Map<string, string>();
  const afterTripRoute = new Map<string, string>();
  for (const [routeId, r] of Object.entries(before)) {
    for (const s of r.stops ?? []) {
      if (s.trip_id && s.stop_type === "pickup") beforeTripRoute.set(s.trip_id, routeId);
    }
  }
  for (const [routeId, r] of Object.entries(after)) {
    for (const s of r.stops ?? []) {
      if (s.trip_id && s.stop_type === "pickup") afterTripRoute.set(s.trip_id, routeId);
    }
  }

  const ids = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return ids.map((routeId) => {
    const b = before[routeId];
    const a = after[routeId];
    const beforeStops = b?.stops ?? [];
    const afterStops = a?.stops ?? [];

    const bKeys = new Set(beforeStops.map(stopKey));
    const aKeys = new Set(afterStops.map(stopKey));
    const added = afterStops.filter((s) => !bKeys.has(stopKey(s)));
    const removed = beforeStops.filter((s) => !aKeys.has(stopKey(s)));

    const movedIn = moved.filter((m) => afterTripRoute.get(m.tripId) === routeId);
    const movedOut = moved.filter((m) => beforeTripRoute.get(m.tripId) === routeId);

    const seqBefore = beforeStops.map((s) => `${stopKey(s)}@${s.sequence}`).join("|");
    const seqAfter = afterStops.map((s) => `${stopKey(s)}@${s.sequence}`).join("|");
    const stopsDifferent =
      added.length > 0 || removed.length > 0 || seqBefore !== seqAfter;

    const state: RoutePlanDiffRow["state"] = !b
      ? "new"
      : !a
        ? "removed"
        : stopsDifferent
          ? "changed"
          : "unchanged";

    return {
      routeId,
      name: (a ?? b)?.name ?? routeId.slice(0, 8),
      vehicleId: (a ?? b)?.vehicle_id ?? null,
      beforeStops,
      afterStops,
      added,
      removed,
      movedIn,
      movedOut,
      state,
    };
  });
}

const STATE_BADGE: Record<RoutePlanDiffRow["state"], { label: string; cls: string }> = {
  changed: { label: "rescheduled", cls: "bg-teal-500/15 text-teal-300 border-teal-500/40" },
  unchanged: { label: "unchanged", cls: "bg-slate-500/10 text-slate-400 border-slate-600/40" },
  new: { label: "opened", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40" },
  removed: { label: "closed", cls: "bg-rose-500/15 text-rose-300 border-rose-500/40" },
};

/** A single stop rendered as a chip: + added, − removed, grey kept. */
function StopChip({ stop, change }: { stop: LnsSnapshotStop; change: "added" | "removed" | "kept" }) {
  const cls =
    change === "added"
      ? "bg-emerald-500/20 border-emerald-500/60 text-emerald-200"
      : change === "removed"
        ? "bg-rose-500/20 border-rose-500/60 text-rose-300 line-through opacity-70"
        : "bg-slate-800 border-slate-700 text-slate-300";
  const tag = stop.stop_type === "pickup" ? "P" : stop.stop_type === "delivery" ? "D" : "W";
  const marker = change === "added" ? "+" : change === "removed" ? "−" : "";
  return (
    <span
      title={`#${stop.sequence} ${stop.stop_type}${stop.trip_id ? ` — ${stop.trip_id}` : ""}`}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-semibold tnum ${cls}`}
    >
      <span>{marker}{tag}</span>
      <span className="opacity-70">{stop.sequence}</span>
    </span>
  );
}

/** Merged, sequence-ordered chips for a route: after-plan order with removed stops appended. */
function planChips(row: RoutePlanDiffRow): { stop: LnsSnapshotStop; change: "added" | "removed" | "kept" }[] {
  const aKeys = new Set(row.afterStops.map(stopKey));
  const bKeys = new Set(row.beforeStops.map(stopKey));
  const chips: { stop: LnsSnapshotStop; change: "added" | "removed" | "kept" }[] = row.afterStops.map(
    (s) => ({ stop: s, change: bKeys.has(stopKey(s)) ? "kept" : "added" }),
  );
  for (const s of row.beforeStops) {
    if (!aKeys.has(stopKey(s))) chips.push({ stop: s, change: "removed" });
  }
  chips.sort((x, y) => {
    const xs = x.change === "removed" ? 9999 : x.stop.sequence ?? 0;
    const ys = y.change === "removed" ? 9999 : y.stop.sequence ?? 0;
    return xs - ys;
  });
  return chips;
}

/** Expandable per-route rows with a stop-level before/after diff. */
function RoutePlanDiff({ rows }: { rows: RoutePlanDiffRow[] }) {
  const changedIds = useMemo(
    () => new Set(rows.filter((r) => r.state !== "unchanged").map((r) => r.routeId)),
    [rows],
  );
  const [expanded, setExpanded] = useState<Set<string>>(changedIds);
  useEffect(() => setExpanded(changedIds), [changedIds]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-1.5">
      {rows.map((row) => {
        const isOpen = expanded.has(row.routeId);
        const chips = planChips(row);
        const moved = row.movedIn.length + row.movedOut.length;
        return (
          <div key={row.routeId} className="rounded-lg border border-slate-800 overflow-hidden bg-slate-950/60">
            <button
              onClick={() => toggle(row.routeId)}
              className="w-full flex items-center justify-between gap-2 px-3 py-2 hover:bg-slate-900/60 text-left"
            >
              <span className="flex items-center gap-2 min-w-0">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: colorForRouteId(row.routeId) }} />
                <span className="text-xs font-semibold text-slate-200 truncate">{row.name}</span>
                <span className="text-[9px] text-slate-500 tnum shrink-0">{row.vehicleId ?? "—"}</span>
              </span>
              <span className="flex items-center gap-2 shrink-0">
                <span className="text-[10px] tnum text-slate-500">
                  {row.beforeStops.length} → {row.afterStops.length}
                </span>
                {row.removed.length > 0 && (
                  <span className="text-[10px] font-bold text-rose-400">−{row.removed.length}</span>
                )}
                {row.added.length > 0 && (
                  <span className="text-[10px] font-bold text-emerald-400">+{row.added.length}</span>
                )}
                {moved > 0 && <span className="text-[10px] font-bold text-amber-300">⇄{moved}</span>}
                <span className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${STATE_BADGE[row.state].cls}`}>
                  {STATE_BADGE[row.state].label}
                </span>
                <span className="text-slate-600 text-xs w-3 text-center">{isOpen ? "−" : "+"}</span>
              </span>
            </button>

            {isOpen && (
              <div className="px-3 py-2.5 border-t border-slate-800 space-y-2">
                {moved > 0 && (
                  <div className="space-y-0.5 text-[10px]">
                    {row.movedOut.map((m) => (
                      <div key={`o-${m.tripId}`} className="flex items-center gap-1.5 text-rose-300">
                        <span>⇡</span>
                        <span className="tnum">{m.tripId}</span>
                        <span className="text-rose-300/70">left this route</span>
                      </div>
                    ))}
                    {row.movedIn.map((m) => (
                      <div key={`i-${m.tripId}`} className="flex items-center gap-1.5 text-emerald-300">
                        <span>⇣</span>
                        <span className="tnum">{m.tripId}</span>
                        <span className="text-emerald-300/70">joined this route</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap gap-1">
                  {chips.map((c, i) => (
                    <StopChip key={`${c.stop.stop_id}-${i}`} stop={c.stop} change={c.change} />
                  ))}
                </div>
                <p className="text-[9px] text-slate-600 pt-1 border-t border-slate-800/60">
                  <span className="text-emerald-400">+</span> added · <span className="text-rose-400">−</span> removed · grey = unchanged · P pickup · D delivery
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Plain-language "what happened" summary at the top of the panel. */
function WhatChangedSection({
  movedRows,
  routeChangeLines,
}: {
  movedRows: { tripId: string; fromLabel: string; toLabel: string }[];
  routeChangeLines: string[];
}) {
  if (movedRows.length === 0 && routeChangeLines.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-xs text-slate-500">
        No trips were moved and no route plans changed — the optimizer kept the existing plan.
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-slate-800 overflow-hidden">
      <div className="px-3 py-2 bg-slate-900/80 border-b border-slate-800 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
        What changed
      </div>
      <div className="divide-y divide-slate-800/70 bg-slate-950/40">
        {movedRows.length > 0 && (
          <div className="px-3 py-2">
            <div className="text-[9px] uppercase tracking-[0.12em] text-slate-600 mb-1">
              Trips moved between routes ({movedRows.length})
            </div>
            <div className="space-y-1">
              {movedRows.map((m) => (
                <div key={m.tripId} className="flex items-center gap-2 text-[11px]">
                  <span className="text-amber-300">⇄</span>
                  <span className="tnum font-semibold text-slate-200">{m.tripId}</span>
                  <span className="text-slate-500">{m.fromLabel}</span>
                  <span className="text-slate-600">→</span>
                  <span className="text-slate-200">{m.toLabel}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {routeChangeLines.length > 0 && (
          <div className="px-3 py-2">
            <div className="text-[9px] uppercase tracking-[0.12em] text-slate-600 mb-1">
              Route plan changes ({routeChangeLines.length})
            </div>
            <div className="space-y-1">
              {routeChangeLines.map((ln, i) => (
                <div key={i} className="text-[11px] text-slate-400">{ln}</div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

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
  const movedTrips = useMemo(() => (run ? computeMovedTrips(run) : []), [run]);
  const detailed = useMemo(() => (run ? buildDetailedDiff(run) : []), [run]);

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
            movedTrips={movedTrips}
            detailed={detailed}
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
  movedTrips,
  detailed,
  mode,
  replayNonce,
  onReplay,
  setMode,
}: {
  run: LnsRun;
  accepted: boolean;
  movedTrips: MovedTrip[];
  detailed: RoutePlanDiffRow[];
  mode: ViewMode;
  replayNonce: number;
  onReplay: () => void;
  setMode: (m: ViewMode) => void;
}) {
  const routeNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const [rid, r] of Object.entries(run.routes_before ?? {})) names.set(rid, r.name ?? rid.slice(0, 8));
    for (const [rid, r] of Object.entries(run.routes_after ?? {})) names.set(rid, r.name ?? rid.slice(0, 8));
    return names;
  }, [run]);

  const beforeTripRoute = useMemo(() => {
    const map = new Map<string, string>();
    for (const [rid, r] of Object.entries(run.routes_before ?? {})) {
      for (const s of r.stops ?? []) if (s.trip_id && s.stop_type === "pickup") map.set(s.trip_id, rid);
    }
    return map;
  }, [run]);

  const afterTripRoute = useMemo(() => {
    const map = new Map<string, string>();
    for (const [rid, r] of Object.entries(run.routes_after ?? {})) {
      for (const s of r.stops ?? []) if (s.trip_id && s.stop_type === "pickup") map.set(s.trip_id, rid);
    }
    return map;
  }, [run]);

  const movedRows = movedTrips.map((m) => ({
    tripId: m.tripId,
    fromLabel: routeNames.get(beforeTripRoute.get(m.tripId) ?? "") ?? "…",
    toLabel: routeNames.get(afterTripRoute.get(m.tripId) ?? "") ?? "…",
  }));

  const routeChangeLines = detailed
    .filter((r) => r.state === "changed")
    .map((r) => {
      const parts: string[] = [];
      if (r.added.length) parts.push(`+${r.added.length} stop${r.added.length === 1 ? "" : "s"}`);
      if (r.removed.length) parts.push(`−${r.removed.length} stop${r.removed.length === 1 ? "" : "s"}`);
      if (r.movedOut.length) parts.push(`${r.movedOut.length} trip${r.movedOut.length === 1 ? "" : "s"} left`);
      if (r.movedIn.length) parts.push(`${r.movedIn.length} trip${r.movedIn.length === 1 ? "" : "s"} joined`);
      return `${r.name}: ${parts.join(" · ")}`;
    });

  const changedRouteCount = detailed.filter((r) => r.state !== "unchanged").length;

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
          {run.destroy_strategy ?? "—"} · repair: {run.repair_strategy ?? "—"} ·{" "}
          {(run.execution_time_ms / 1000).toFixed(1)}s ·{" "}
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
        <MetricCell label="Routes touched" value={String(changedRouteCount)} />
        <MetricCell label="Trips moved" value={String(movedTrips.length)} />
      </div>

      {/* What changed */}
      <WhatChangedSection movedRows={movedRows} routeChangeLines={routeChangeLines} />

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

      {/* Per-route plan diff */}
      <div>
        <h3 className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500 mb-2">
          Route plans — before / after ({detailed.length} routes)
        </h3>
        <RoutePlanDiff rows={detailed} />
      </div>
    </div>
  );
}