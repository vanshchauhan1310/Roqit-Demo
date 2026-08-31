import { useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { assignRoute, optimizeRouteOrder, reorderRouteStops } from "@/api/routes";
import { useUnassignedTrips } from "@/hooks/useUnassignedTrips";
import { useTrips } from "@/hooks/useTrips";
import { useDriverRoster } from "@/hooks/useDriverRoster";
import { useVehicleRoster } from "@/hooks/useVehicleRoster";
import { useRoadRoute } from "@/hooks/useRoadRoute";
import { RouteMapPreview } from "./RouteMapPreview";
import type { Trip } from "@/types/trip";
import type { DriverRosterItem, VehicleRosterItem } from "@/types/roster";
import type { OptimizeStopInput } from "@/types/optimize";
import {
  IconAlertTriangle,
  IconArrowDown,
  IconArrowUp,
  IconCheck,
  IconFuel,
  IconShield,
  IconStar,
  IconX,
} from "@/components/common/icons";

interface CreateRouteModalProps {
  open: boolean;
  onClose: () => void;
}

interface StopPreview {
  tripId: string;
  stopType: "pickup" | "delivery";
}

interface TripLoad {
  weightKg: string;
  value: string;
}

const STEP_LABELS = ["Driver", "Vehicle", "Filter & Validate", "Trips", "Review"];
const LAST_STEP = STEP_LABELS.length - 1;

function buildDefaultStops(tripIds: string[]): StopPreview[] {
  return [
    ...tripIds.map((tripId) => ({ tripId, stopType: "pickup" as const })),
    ...tripIds.map((tripId) => ({ tripId, stopType: "delivery" as const })),
  ];
}

function precedenceViolation(stops: StopPreview[]): boolean {
  const pickupIndex = new Map<string, number>();
  for (let i = 0; i < stops.length; i++) {
    if (stops[i].stopType === "pickup") pickupIndex.set(stops[i].tripId, i);
  }
  for (let i = 0; i < stops.length; i++) {
    const stop = stops[i];
    if (stop.stopType !== "delivery") continue;
    const pIndex = pickupIndex.get(stop.tripId);
    if (pIndex != null && pIndex > i) return true;
  }
  return false;
}

function sameOrder(a: StopPreview[], b: StopPreview[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((stop, i) => stop.tripId === b[i].tripId && stop.stopType === b[i].stopType);
}

// Peak concurrent load along the ACTUAL chosen stop order - not a flat sum of every trip's
// weight. A sequential pickup->drop->pickup->drop order never carries more than its single
// heaviest trip at once, even if the trips' weights summed would exceed capacity; a flat-sum
// check can't tell the two cases apart and wrongly blocks a genuinely feasible route. Mirrors
// backend route_service.py::_max_cumulative_load_kg / ml/src/optimizer/opt.py::_load_at_positions
// (see WEIGHT_AWARE_ROUTING.md §8).
function peakConcurrentLoadKg(stops: StopPreview[], loads: Record<string, TripLoad>, tripsById: Map<string, Trip>): number {
  let running = 0;
  let peak = 0;
  for (const stop of stops) {
    const entered = loads[stop.tripId]?.weightKg;
    const weight = entered ? Number(entered) : (tripsById.get(stop.tripId)?.load_weight_kg ?? 0);
    running += stop.stopType === "pickup" ? weight : -weight;
    peak = Math.max(peak, running);
  }
  return peak;
}

type IneligibilityReason = "already-assigned" | "exceeds-vehicle-capacity";

// Layered ON TOP of the existing "already assigned" rule (unassignedTripIds - unchanged, still
// the sole source of truth for that check) - adds a new, additive vehicle/load eligibility check.
// This does NOT touch pickup/delivery precedence at all: precedence is a property of the chosen
// STOP ORDER, validated exactly as before (moveStop's precedenceViolation, the backend's
// _validate_precedence on reorder, and opt.py's route_is_feasible in the solver) - none of that
// logic is duplicated or altered here. This only pre-filters which trips are selectable, the same
// way "a trip already on a route can't be selected" always has.
function tripIneligibilityReason(
  trip: Trip,
  unassignedTripIds: Set<string>,
  selectedTripIds: string[],
  vehicleCapacityKg: number | null,
  loads: Record<string, TripLoad>,
): IneligibilityReason | null {
  const alreadySelected = selectedTripIds.includes(trip.trip_id);
  if (!unassignedTripIds.has(trip.trip_id) && !alreadySelected) return "already-assigned";
  if (vehicleCapacityKg != null) {
    const entered = loads[trip.trip_id]?.weightKg;
    const weight = entered ? Number(entered) : trip.load_weight_kg;
    // Mirrors the backend's own "could this trip ever fit, in any stop order" pre-check
    // (route_service.py's assign_route: heaviest single trip vs vehicle.load_capacity_kg) -
    // not a new rule, the same existence check, just evaluated per-trip before selection here.
    if (weight != null && weight > vehicleCapacityKg) return "exceeds-vehicle-capacity";
  }
  return null;
}

export function CreateRouteModal({ open, onClose }: CreateRouteModalProps) {
  const [step, setStep] = useState(0);
  const [selectedTripIds, setSelectedTripIds] = useState<string[]>([]);
  const [stops, setStops] = useState<StopPreview[]>([]);
  const [driverId, setDriverId] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [loads, setLoads] = useState<Record<string, TripLoad>>({});
  const [pickupDateTime, setPickupDateTime] = useState("");
  const [routeName, setRouteName] = useState("");

  const queryClient = useQueryClient();
  // Shows every trip (not just unassigned ones - a trip already on a route is
  // still visible here, matching how DriverStep/VehicleStep below show every
  // driver/vehicle and just disable+badge the unavailable ones, rather than
  // hiding them). unassignedTrips is only consulted to know WHICH trips are
  // already routed - selecting one is blocked, since the backend has no
  // safeguard against the same trip's pickup+delivery ending up on two routes.
  const { data: trips, isLoading: tripsLoading } = useTrips(1, {});
  const { data: unassignedTrips } = useUnassignedTrips();
  const { data: drivers, isLoading: driversLoading } = useDriverRoster();
  const { data: vehicles, isLoading: vehiclesLoading } = useVehicleRoster();

  const unassignedTripIds = useMemo(
    () => new Set((unassignedTrips ?? []).map((t) => t.trip_id)),
    [unassignedTrips],
  );

  const tripsById = useMemo(() => new Map((trips ?? []).map((t) => [t.trip_id, t])), [trips]);
  const selectedDriver = drivers?.find((d) => d.driver_id === driverId) ?? null;
  const selectedVehicle = vehicles?.find((v) => v.vehicle_id === vehicleId) ?? null;

  const defaultStops = useMemo(() => buildDefaultStops(selectedTripIds), [selectedTripIds]);
  const reordered = !sameOrder(stops, defaultStops);

  const mapStops = useMemo(
    () =>
      stops
        .map((stop, i) => {
          const trip = tripsById.get(stop.tripId);
          const lat = stop.stopType === "pickup" ? trip?.gps_start_lat : trip?.gps_end_lat;
          const lng = stop.stopType === "pickup" ? trip?.gps_start_lon : trip?.gps_end_lon;
          if (lat == null || lng == null) return null;
          return {
            key: `${stop.tripId}:${stop.stopType}`,
            lat,
            lng,
            label: `${stop.stopType === "pickup" ? "Pickup" : "Delivery"} · ${trip?.trip_id ?? ""}`,
            sequence: i + 1,
          };
        })
        .filter((s): s is NonNullable<typeof s> => s !== null),
    [stops, tripsById],
  );

  const roadRoute = useRoadRoute(mapStops.map((s) => [s.lat, s.lng] as [number, number]));

  const stopsMissingCoordinates = stops.some((stop) => {
    const trip = tripsById.get(stop.tripId);
    const lat = stop.stopType === "pickup" ? trip?.gps_start_lat : trip?.gps_end_lat;
    const lng = stop.stopType === "pickup" ? trip?.gps_start_lon : trip?.gps_end_lon;
    return lat == null || lng == null;
  });

  const optimizeMutation = useMutation({
    mutationFn: async () => {
      const stopInputs: OptimizeStopInput[] = stops.map((stop) => {
        const trip = tripsById.get(stop.tripId);
        const lat = stop.stopType === "pickup" ? trip?.gps_start_lat : trip?.gps_end_lat;
        const lng = stop.stopType === "pickup" ? trip?.gps_start_lon : trip?.gps_end_lon;
        const enteredWeight = loads[stop.tripId]?.weightKg;
        return {
          key: `${stop.tripId}:${stop.stopType}`,
          latitude: lat ?? 0,
          longitude: lng ?? 0,
          trip_id: stop.tripId,
          stop_type: stop.stopType,
          load_weight_kg: enteredWeight ? Number(enteredWeight) : (trip?.load_weight_kg ?? null),
        };
      });
      const fuelPricePerL = selectedTripIds
        .map((id) => tripsById.get(id)?.fuel_price_per_l)
        .find((v): v is number => v != null) ?? null;
      return optimizeRouteOrder(
        stopInputs,
        selectedVehicle?.load_capacity_kg ?? null,
        selectedVehicle?.avg_kmpl_rated ?? null,
        fuelPricePerL,
      );
    },
    onSuccess: (result) => {
      const byKey = new Map(stops.map((s) => [`${s.tripId}:${s.stopType}`, s]));
      const nextStops = result.order.map((key) => byKey.get(key)).filter((s): s is StopPreview => Boolean(s));
      if (nextStops.length === stops.length) setStops(nextStops);
    },
  });

  const totalLoadKg = selectedTripIds.reduce(
    (sum, tripId) => sum + (Number(loads[tripId]?.weightKg) || 0),
    0,
  );
  const peakLoadKg = useMemo(
    () => peakConcurrentLoadKg(stops, loads, tripsById),
    [stops, loads, tripsById],
  );
  const exceedsCapacity =
    selectedVehicle?.load_capacity_kg != null && peakLoadKg > selectedVehicle.load_capacity_kg;

  const mutation = useMutation({
    mutationFn: async () => {
      const route = await assignRoute({
        trip_ids: selectedTripIds,
        driver_id: driverId,
        vehicle_id: vehicleId,
        pickup_time: new Date(pickupDateTime).toISOString(),
        name: routeName || null,
        loads: selectedTripIds.map((tripId) => ({
          trip_id: tripId,
          load_weight_kg: loads[tripId]?.weightKg ? Number(loads[tripId].weightKg) : null,
          load_value: loads[tripId]?.value ? Number(loads[tripId].value) : null,
        })),
      });

      if (reordered) {
        const byKey = new Map(route.stops.map((s) => [`${s.trip_id}:${s.stop_type}`, s.stop_id]));
        const orderedStopIds = stops
          .map((s) => byKey.get(`${s.tripId}:${s.stopType}`))
          .filter((id): id is string => Boolean(id));
        if (orderedStopIds.length === route.stops.length) {
          await reorderRouteStops(route.route_id, { stop_ids: orderedStopIds });
        }
      }
      return route;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      queryClient.invalidateQueries({ queryKey: ["trips", "unassigned"] });
      queryClient.invalidateQueries({ queryKey: ["routes"] });
      resetAndClose();
    },
  });

  if (!open) return null;

  const resetAndClose = () => {
    setStep(0);
    setSelectedTripIds([]);
    setStops([]);
    setDriverId("");
    setVehicleId("");
    setLoads({});
    setPickupDateTime("");
    setRouteName("");
    onClose();
  };

  const toggleTrip = (tripId: string) => {
    const wasSelected = selectedTripIds.includes(tripId);
    if (!wasSelected) {
      const trip = tripsById.get(tripId);
      const reason = trip
        ? tripIneligibilityReason(trip, unassignedTripIds, selectedTripIds, selectedVehicle?.load_capacity_kg ?? null, loads)
        : "already-assigned";
      if (reason) return; // not eligible - already on a route, or alone exceeds this vehicle's capacity
    }
    const next = wasSelected ? selectedTripIds.filter((id) => id !== tripId) : [...selectedTripIds, tripId];
    setSelectedTripIds(next);
    setStops(buildDefaultStops(next));

    if (!wasSelected) {
      // Reuse the weight already captured at trip creation, if any - don't force
      // re-entering something already known (see WEIGHT_AWARE_ROUTING.md).
      const existingWeight = tripsById.get(tripId)?.load_weight_kg;
      if (existingWeight != null) {
        setLoads((prev) => ({
          ...prev,
          [tripId]: { weightKg: prev[tripId]?.weightKg ?? String(existingWeight), value: prev[tripId]?.value ?? "" },
        }));
      }
    }
  };

  const moveStop = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= stops.length) return;
    const next = [...stops];
    [next[index], next[target]] = [next[target], next[index]];
    if (precedenceViolation(next)) return;
    setStops(next);
  };

  const updateLoad = (tripId: string, patch: Partial<TripLoad>) =>
    setLoads((prev) => ({ ...prev, [tripId]: { ...(prev[tripId] ?? { weightKg: "", value: "" }), ...patch } }));

  const canContinue = (): boolean => {
    if (step === 0) return Boolean(selectedDriver);
    if (step === 1) return Boolean(selectedVehicle);
    if (step === 2) return true; // filter/validate is informational, never blocks
    if (step === 3) return selectedTripIds.length >= 2 && !exceedsCapacity;
    return pickupDateTime.trim() !== "";
  };

  const mutationErrorMessage =
    mutation.isError && isAxiosError(mutation.error) && typeof mutation.error.response?.data?.detail === "string"
      ? mutation.error.response.data.detail
      : mutation.isError
        ? "Something went wrong assigning this route. Please try again."
        : null;

  const optimizeErrorMessage =
    optimizeMutation.isError && isAxiosError(optimizeMutation.error) && typeof optimizeMutation.error.response?.data?.detail === "string"
      ? optimizeMutation.error.response.data.detail
      : optimizeMutation.isError
        ? "Couldn't optimize the stop order. Try again."
        : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="flex items-start justify-between px-6 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Create Route</h2>
            <p className="text-sm text-gray-500 mt-0.5">Group trips into a dispatched run — driver, vehicle and pickup time in one go.</p>
          </div>
          <button onClick={resetAndClose} className="text-gray-400 hover:text-gray-600">
            <IconX />
          </button>
        </div>

        <div className="px-6 pt-5">
          <StepIndicator current={step} />
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            {step === 0 && (
              <DriverStep
                drivers={drivers ?? []}
                isLoading={driversLoading}
                selectedDriverId={driverId}
                onSelectDriver={setDriverId}
              />
            )}
            {step === 1 && (
              <VehicleStep
                vehicles={vehicles ?? []}
                isLoading={vehiclesLoading}
                selectedVehicleId={vehicleId}
                onSelectVehicle={setVehicleId}
              />
            )}
            {step === 2 && (
              <FilterValidateStep
                trips={trips ?? []}
                isLoading={tripsLoading}
                unassignedTripIds={unassignedTripIds}
                selectedTripIds={selectedTripIds}
                vehicleCapacityKg={selectedVehicle?.load_capacity_kg ?? null}
                loads={loads}
                onUpdateLoad={updateLoad}
              />
            )}
            {step === 3 && (
              <TripsStep
                trips={trips ?? []}
                isLoading={tripsLoading}
                selectedTripIds={selectedTripIds}
                unassignedTripIds={unassignedTripIds}
                vehicleCapacityKg={selectedVehicle?.load_capacity_kg ?? null}
                loads={loads}
                onToggleTrip={toggleTrip}
                stops={stops}
                onMoveStop={moveStop}
                totalLoadKg={totalLoadKg}
                peakLoadKg={peakLoadKg}
                exceedsCapacity={exceedsCapacity}
                onOptimize={() => optimizeMutation.mutate()}
                isOptimizing={optimizeMutation.isPending}
                optimizeDisabled={stopsMissingCoordinates || stops.length < 4}
                solverUsed={optimizeMutation.data?.solver_used ?? null}
                optimizeErrorMessage={optimizeErrorMessage}
              />
            )}
            {step === 4 && (
              <ReviewStep
                trips={selectedTripIds.map((id) => tripsById.get(id)).filter((t): t is Trip => Boolean(t))}
                driver={selectedDriver}
                vehicle={selectedVehicle}
                loads={loads}
                totalLoadKg={totalLoadKg}
                distanceKm={roadRoute.distanceKm ?? 0}
                durationHours={roadRoute.durationHours ?? 0}
                pickupDateTime={pickupDateTime}
                onPickupDateTimeChange={setPickupDateTime}
                routeName={routeName}
                onRouteNameChange={setRouteName}
                reordered={reordered}
              />
            )}
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex flex-col h-[320px]">
              <RouteMapPreview
                stops={mapStops}
                routeGeometry={roadRoute.geometry}
                isRouteLoading={roadRoute.isLoading}
                isRouteError={roadRoute.isError}
                emptyLabel="Select trips to preview them on the map"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <SummaryStat
                label="Total distance"
                value={roadRoute.distanceKm != null ? `${Math.round(roadRoute.distanceKm)} km` : "—"}
              />
              <SummaryStat
                label="Est. duration"
                value={roadRoute.durationHours != null ? `${roadRoute.durationHours.toFixed(1)} h` : "—"}
              />
            </div>
            {selectedTripIds.length > 0 && roadRoute.distanceKm == null && !roadRoute.isLoading && (
              <p className="text-xs text-amber-600">
                Distance unavailable — some trips aren't geocoded, so the road route can't be drawn.
              </p>
            )}
          </div>
        </div>

        {mutationErrorMessage && (
          <div className="mx-6 mb-3 px-4 py-2.5 rounded-lg bg-red-50 border border-red-100 text-sm text-red-700">
            {mutationErrorMessage}
          </div>
        )}

        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100">
          <button
            onClick={() => setStep((s) => Math.max(s - 1, 0))}
            disabled={step === 0 || mutation.isPending}
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 disabled:text-gray-300 disabled:cursor-not-allowed"
          >
            Back
          </button>

          {step < LAST_STEP ? (
            <button
              onClick={() => setStep((s) => Math.min(s + 1, LAST_STEP))}
              disabled={!canContinue()}
              className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Continue
            </button>
          ) : (
            <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || !canContinue()}
              className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50"
            >
              {mutation.isPending ? "Assigning…" : "Assign route"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center">
      {STEP_LABELS.map((label, i) => (
        <div key={label} className={`flex items-center ${i < STEP_LABELS.length - 1 ? "flex-1" : ""}`}>
          <div className="flex items-center gap-2">
            <span
              className={`w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold ${
                i < current
                  ? "bg-emerald-500 text-white"
                  : i === current
                    ? "bg-teal-600 text-white"
                    : "bg-gray-100 text-gray-400"
              }`}
            >
              {i < current ? <IconCheck /> : i + 1}
            </span>
            <span className={`text-sm font-medium whitespace-nowrap ${i <= current ? "text-gray-900" : "text-gray-400"}`}>
              {label}
            </span>
          </div>
          {i < STEP_LABELS.length - 1 && (
            <div className={`flex-1 h-px mx-3 ${i < current ? "bg-emerald-300" : "bg-gray-200"}`} />
          )}
        </div>
      ))}
    </div>
  );
}

interface TripsStepProps {
  trips: Trip[];
  isLoading: boolean;
  selectedTripIds: string[];
  unassignedTripIds: Set<string>;
  vehicleCapacityKg: number | null;
  loads: Record<string, TripLoad>;
  onToggleTrip: (tripId: string) => void;
  stops: StopPreview[];
  onMoveStop: (index: number, direction: -1 | 1) => void;
  totalLoadKg: number;
  peakLoadKg: number;
  exceedsCapacity: boolean;
  onOptimize: () => void;
  isOptimizing: boolean;
  optimizeDisabled: boolean;
  solverUsed: "exact" | "hybrid" | null;
  optimizeErrorMessage: string | null;
}

function TripsStep({
  trips,
  isLoading,
  selectedTripIds,
  unassignedTripIds,
  vehicleCapacityKg,
  loads,
  onToggleTrip,
  stops,
  onMoveStop,
  totalLoadKg,
  peakLoadKg,
  exceedsCapacity,
  onOptimize,
  isOptimizing,
  optimizeDisabled,
  solverUsed,
  optimizeErrorMessage,
}: TripsStepProps) {
  return (
    <div className="space-y-5">
      <div>
        <label className="block text-sm font-semibold text-gray-900 mb-2">Select trips to group (min 2)</label>
        <p className="text-xs text-gray-400 mb-2">Only trips that passed Filter &amp; Validate are selectable.</p>
        {isLoading && <p className="text-sm text-gray-400">Loading trips…</p>}
        {!isLoading && trips.length === 0 && (
          <p className="text-sm text-gray-400">No trips available — create a trip first.</p>
        )}
        <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
          {trips.map((trip) => {
            const selected = selectedTripIds.includes(trip.trip_id);
            const reason = selected
              ? null
              : tripIneligibilityReason(trip, unassignedTripIds, selectedTripIds, vehicleCapacityKg, loads);
            const ineligible = reason != null;
            return (
              <button
                key={trip.trip_id}
                type="button"
                onClick={() => onToggleTrip(trip.trip_id)}
                disabled={ineligible}
                className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-lg border text-left transition-colors ${
                  selected
                    ? "border-teal-500 bg-teal-50"
                    : ineligible
                      ? "border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed"
                      : "border-gray-200 hover:bg-gray-50"
                }`}
              >
                <div>
                  <div className="text-sm font-medium text-gray-900">
                    {trip.trip_id} · {trip.origin ?? "—"} → {trip.destination ?? "—"}
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {trip.load_weight_kg != null ? `${trip.load_weight_kg.toLocaleString()} kg` : "No load yet"}
                    {trip.planned_distance_km != null ? ` · ${Math.round(trip.planned_distance_km)} km` : ""}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {reason === "already-assigned" && (
                    <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium whitespace-nowrap">
                      Assigned
                    </span>
                  )}
                  {reason === "exceeds-vehicle-capacity" && (
                    <span className="px-2.5 py-1 rounded-full bg-red-50 text-red-700 text-xs font-medium whitespace-nowrap">
                      Exceeds capacity
                    </span>
                  )}
                  <span
                    className={`w-5 h-5 shrink-0 rounded border flex items-center justify-center ${
                      selected ? "bg-teal-600 border-teal-600 text-white" : "border-gray-300 text-transparent"
                    }`}
                  >
                    <IconCheck />
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {stops.length >= 2 && (
        <div>
          <label className="block text-sm font-semibold text-gray-900 mb-2">
            Stop sequence <span className="text-gray-400 font-normal">(reorder with arrows — a delivery can never precede its own pickup)</span>
          </label>
          <p className="text-xs text-gray-400 mb-2">
            Reorder manually with the arrows, or use Optimize below — it weighs distance, travel time, fuel cost and
            cargo weight together, using the driver/vehicle/load already set.
          </p>
          <div className="space-y-2">
            {stops.map((stop, index) => {
              const trip = trips.find((t) => t.trip_id === stop.tripId);
              return (
                <div key={`${stop.tripId}:${stop.stopType}`} className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-gray-200 bg-white">
                  <span className="w-6 h-6 rounded-full bg-sky-100 text-sky-700 text-xs font-semibold flex items-center justify-center shrink-0">
                    {index + 1}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-medium shrink-0 ${
                      stop.stopType === "pickup" ? "bg-sky-50 text-sky-700" : "bg-emerald-50 text-emerald-700"
                    }`}
                  >
                    {stop.stopType === "pickup" ? "Pickup" : "Delivery"}
                  </span>
                  <span className="text-sm text-gray-700 truncate">
                    {stop.stopType === "pickup" ? trip?.origin ?? "—" : trip?.destination ?? "—"}
                    <span className="text-gray-400"> · {stop.tripId}</span>
                  </span>
                  <div className="flex gap-1 ml-auto shrink-0">
                    <button
                      onClick={() => onMoveStop(index, -1)}
                      disabled={index === 0}
                      className="p-1.5 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <IconArrowUp />
                    </button>
                    <button
                      onClick={() => onMoveStop(index, 1)}
                      disabled={index === stops.length - 1}
                      className="p-1.5 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <IconArrowDown />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          <div
            className={`mt-3 px-4 py-3 rounded-lg border text-sm ${
              exceedsCapacity ? "bg-red-50 border-red-100 text-red-700" : "bg-gray-50 border-gray-200 text-gray-600"
            }`}
          >
            {vehicleCapacityKg != null ? (
              exceedsCapacity ? (
                <>
                  This stop order carries <strong>{peakLoadKg.toLocaleString()} kg</strong> at once, exceeding this
                  vehicle's {vehicleCapacityKg.toLocaleString()} kg capacity — reduce a load, pick a different
                  vehicle, or optimize the stop order below so fewer pickups overlap before their deliveries.
                </>
              ) : (
                <>
                  Peak load carried at once: <strong>{peakLoadKg.toLocaleString()} kg</strong> of{" "}
                  {vehicleCapacityKg.toLocaleString()} kg vehicle capacity
                  {peakLoadKg > 0 ? ` (${Math.round((peakLoadKg / vehicleCapacityKg) * 100)}%)` : ""}
                  {totalLoadKg !== peakLoadKg ? ` — ${totalLoadKg.toLocaleString()} kg total across all trips` : ""}
                </>
              )
            ) : (
              <>Combined load: {totalLoadKg.toLocaleString()} kg total across all trips</>
            )}
          </div>

          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-xs text-gray-400">
              {solverUsed
                ? `Optimized via the ${solverUsed === "hybrid" ? "hybrid ML+DSA" : "exact"} solver.`
                : "Reorders this route's stops — see the result on the map preview."}
            </p>
            <button
              type="button"
              onClick={onOptimize}
              disabled={optimizeDisabled || isOptimizing}
              title={optimizeDisabled ? "Locate every selected trip's pickup/drop first to enable optimization" : undefined}
              className="shrink-0 px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isOptimizing ? "Optimizing…" : "Optimize stop order"}
            </button>
          </div>
          {optimizeErrorMessage && <p className="mt-2 text-xs text-red-600">{optimizeErrorMessage}</p>}
        </div>
      )}
    </div>
  );
}

interface FilterValidateStepProps {
  trips: Trip[];
  isLoading: boolean;
  unassignedTripIds: Set<string>;
  selectedTripIds: string[];
  vehicleCapacityKg: number | null;
  loads: Record<string, TripLoad>;
  onUpdateLoad: (tripId: string, patch: Partial<TripLoad>) => void;
}

function FilterValidateStep({
  trips,
  isLoading,
  unassignedTripIds,
  selectedTripIds,
  vehicleCapacityKg,
  loads,
  onUpdateLoad,
}: FilterValidateStepProps) {
  const evaluated = trips.map((trip) => ({
    trip,
    reason: tripIneligibilityReason(trip, unassignedTripIds, selectedTripIds, vehicleCapacityKg, loads),
  }));
  const eligibleCount = evaluated.filter((e) => e.reason == null).length;
  const alreadyAssignedCount = evaluated.filter((e) => e.reason === "already-assigned").length;
  const overCapacityCount = evaluated.filter((e) => e.reason === "exceeds-vehicle-capacity").length;

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-semibold text-gray-900 mb-1">Filter &amp; validate trips</label>
        <p className="text-xs text-gray-400 mb-3">
          Existing pickup/drop rules (a trip already on a route can't be reused) plus the driver/vehicle just chosen
          determine which trips are eligible below. Weight is optional — enter it here if known, or leave blank and
          it won't block anything; a weight already captured at trip creation is reused automatically. Stop-order
          precedence (delivery never before its own pickup) is unaffected by this step — it's still enforced exactly
          as before, later, on the actual chosen stop sequence.
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-medium">
            {eligibleCount} eligible
          </span>
          {alreadyAssignedCount > 0 && (
            <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium">
              {alreadyAssignedCount} already assigned
            </span>
          )}
          {overCapacityCount > 0 && (
            <span className="px-2.5 py-1 rounded-full bg-red-50 text-red-700 text-xs font-medium">
              {overCapacityCount} exceed vehicle capacity
            </span>
          )}
        </div>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading trips…</p>}
      {!isLoading && trips.length === 0 && (
        <p className="text-sm text-gray-400">No trips available — create a trip first.</p>
      )}

      <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
        {evaluated.map(({ trip, reason }) => (
          <div
            key={trip.trip_id}
            className={`border rounded-xl p-4 ${reason ? "border-gray-100 bg-gray-50 opacity-75" : "border-gray-200"}`}
          >
            <div className="flex items-center justify-between gap-3 mb-3">
              <div className="text-sm font-medium text-gray-900">
                {trip.trip_id} · {trip.origin ?? "—"} → {trip.destination ?? "—"}
              </div>
              {reason === "already-assigned" && (
                <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium whitespace-nowrap shrink-0">
                  Already assigned
                </span>
              )}
              {reason === "exceeds-vehicle-capacity" && (
                <span className="px-2.5 py-1 rounded-full bg-red-50 text-red-700 text-xs font-medium whitespace-nowrap shrink-0">
                  Exceeds vehicle capacity
                </span>
              )}
              {reason == null && (
                <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-medium whitespace-nowrap shrink-0">
                  Eligible
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">
                  Weight (kg)
                  {trip.load_weight_kg != null && (
                    <span className="ml-1.5 text-xs text-gray-400">
                      on file: {trip.load_weight_kg.toLocaleString()} kg
                    </span>
                  )}
                </label>
                <input
                  type="number"
                  min={0}
                  disabled={reason === "already-assigned"}
                  // Show the stored weight rather than an empty box: `loads` is only
                  // populated once a trip is SELECTED (toggleTrip), which happens a
                  // step later, so binding to it alone renders every field blank here
                  // and reads as "no weight recorded" even when one exists.
                  value={loads[trip.trip_id]?.weightKg ?? (trip.load_weight_kg != null ? String(trip.load_weight_kg) : "")}
                  onChange={(e) => onUpdateLoad(trip.trip_id, { weightKg: e.target.value })}
                  placeholder={trip.load_weight_kg == null ? "Not recorded — optional" : "e.g. 8000"}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm disabled:opacity-50"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">Value (₹)</label>
                <input
                  type="number"
                  min={0}
                  disabled={reason === "already-assigned"}
                  value={loads[trip.trip_id]?.value ?? ""}
                  onChange={(e) => onUpdateLoad(trip.trip_id, { value: e.target.value })}
                  placeholder="e.g. 250000"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm disabled:opacity-50"
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function statusBadgeStyle(status: string | null): string {
  const s = (status ?? "").toLowerCase();
  if (s.includes("avail") || s.includes("active")) return "bg-emerald-50 text-emerald-700";
  if (s.includes("inactive") || s.includes("suspend")) return "bg-red-50 text-red-600";
  if (!s) return "bg-gray-100 text-gray-500";
  return "bg-amber-50 text-amber-700";
}

interface DriverStepProps {
  drivers: DriverRosterItem[];
  isLoading: boolean;
  selectedDriverId: string;
  onSelectDriver: (id: string) => void;
}

function DriverStep({ drivers, isLoading, selectedDriverId, onSelectDriver }: DriverStepProps) {
  return (
    <div>
      <label className="block text-sm font-semibold text-gray-900 mb-2">Assign driver</label>
      {isLoading && <p className="text-sm text-gray-400">Loading drivers…</p>}
      {!isLoading && drivers.length === 0 && <p className="text-sm text-gray-400">No drivers found.</p>}
      <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
        {drivers.map((driver) => {
          const selected = driver.driver_id === selectedDriverId;
          const unavailable = driver.is_on_trip;
          const subtitleParts = [
            driver.driver_id,
            driver.experience_years != null ? `${driver.experience_years} yrs` : null,
            driver.license_type,
          ].filter(Boolean);

          return (
            <button
              key={driver.driver_id}
              type="button"
              onClick={() => !unavailable && onSelectDriver(driver.driver_id)}
              disabled={unavailable}
              className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-lg border text-left transition-colors ${
                selected
                  ? "border-teal-500 bg-teal-50"
                  : unavailable
                    ? "border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed"
                    : "border-gray-200 hover:bg-gray-50"
              }`}
            >
              <div>
                <div className="text-sm font-medium text-gray-900">{driver.driver_name ?? driver.driver_id}</div>
                <div className="text-xs text-gray-500 mt-0.5">{subtitleParts.join(" · ")}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {driver.rating != null && (
                  <span className="flex items-center gap-1 px-2 py-1 rounded-full bg-amber-50 text-amber-600 text-xs font-medium">
                    <IconStar />
                    {driver.rating}
                  </span>
                )}
                <span className={`px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
                  driver.is_on_trip ? "bg-amber-50 text-amber-700" : statusBadgeStyle(driver.status)
                }`}>
                  {driver.is_on_trip ? "On Trip" : (driver.status ?? "Available")}
                </span>
                {driver.license_expiring_soon != null && (
                  <span
                    className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap ${
                      driver.license_expiring_soon ? "bg-red-50 text-red-600" : "bg-emerald-50 text-emerald-700"
                    }`}
                  >
                    {driver.license_expiring_soon ? <IconAlertTriangle /> : <IconShield />}
                    License
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface VehicleStepProps {
  vehicles: VehicleRosterItem[];
  isLoading: boolean;
  selectedVehicleId: string;
  onSelectVehicle: (id: string) => void;
}

function VehicleStep({ vehicles, isLoading, selectedVehicleId, onSelectVehicle }: VehicleStepProps) {
  return (
    <div>
      <label className="block text-sm font-semibold text-gray-900 mb-2">Assign vehicle</label>
      {isLoading && <p className="text-sm text-gray-400">Loading vehicles…</p>}
      {!isLoading && vehicles.length === 0 && <p className="text-sm text-gray-400">No vehicles found.</p>}
      <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
        {vehicles.map((vehicle) => {
          const selected = vehicle.vehicle_id === selectedVehicleId;
          const unavailable = vehicle.is_on_trip;
          const subtitleParts = [
            [vehicle.make, vehicle.model].filter(Boolean).join(" "),
            vehicle.load_capacity_kg != null ? `${vehicle.load_capacity_kg.toLocaleString()} kg capacity` : null,
            vehicle.fuel_type,
          ].filter((part) => Boolean(part && part.trim()));

          return (
            <button
              key={vehicle.vehicle_id}
              type="button"
              onClick={() => !unavailable && onSelectVehicle(vehicle.vehicle_id)}
              disabled={unavailable}
              className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-lg border text-left transition-colors ${
                selected
                  ? "border-teal-500 bg-teal-50"
                  : unavailable
                    ? "border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed"
                    : "border-gray-200 hover:bg-gray-50"
              }`}
            >
              <div>
                <div className="text-sm font-medium text-gray-900">
                  {vehicle.vehicle_id} · {vehicle.vehicle_type ?? "—"}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{subtitleParts.join(" · ")}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {vehicle.is_on_trip && (
                  <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium whitespace-nowrap">
                    In Use
                  </span>
                )}
                {vehicle.avg_kmpl_rated != null && (
                  <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-sky-50 text-sky-700 text-xs font-medium whitespace-nowrap">
                    <IconFuel />
                    {vehicle.avg_kmpl_rated} km/l
                  </span>
                )}
                {vehicle.service_due_soon && (
                  <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium whitespace-nowrap">
                    Service due soon
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface ReviewStepProps {
  trips: Trip[];
  driver: DriverRosterItem | null;
  vehicle: VehicleRosterItem | null;
  loads: Record<string, TripLoad>;
  totalLoadKg: number;
  distanceKm: number;
  durationHours: number;
  pickupDateTime: string;
  onPickupDateTimeChange: (value: string) => void;
  routeName: string;
  onRouteNameChange: (value: string) => void;
  reordered: boolean;
}

function ReviewStep({
  trips,
  driver,
  vehicle,
  loads,
  totalLoadKg,
  distanceKm,
  durationHours,
  pickupDateTime,
  onPickupDateTimeChange,
  routeName,
  onRouteNameChange,
  reordered,
}: ReviewStepProps) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm text-gray-600 mb-1">Pickup time (shared by all trips on this route)</label>
        <input
          type="datetime-local"
          value={pickupDateTime}
          onChange={(e) => onPickupDateTimeChange(e.target.value)}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
        />
      </div>
      <div>
        <label className="block text-sm text-gray-600 mb-1">Route name (optional)</label>
        <input
          type="text"
          value={routeName}
          onChange={(e) => onRouteNameChange(e.target.value)}
          placeholder="e.g. Rotterdam cluster run"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
        />
      </div>

      <div className="border border-gray-200 rounded-xl p-4 space-y-3 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Trips</span>
          <span className="font-medium text-gray-900">
            {trips.map((t) => t.trip_id).join(", ")}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Driver</span>
          <span className="font-medium text-gray-900">
            {driver ? `${driver.driver_name ?? driver.driver_id}` : "—"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Vehicle</span>
          <span className="font-medium text-gray-900">
            {vehicle ? `${vehicle.vehicle_id} · ${vehicle.vehicle_type ?? "—"}` : "—"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Combined load</span>
          <span className="font-medium text-gray-900">
            {totalLoadKg.toLocaleString()} kg
            {vehicle?.load_capacity_kg != null && totalLoadKg > 0
              ? ` / ${vehicle.load_capacity_kg.toLocaleString()} kg`
              : ""}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Est. distance</span>
          <span className="font-medium text-gray-900">{Math.round(distanceKm)} km</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Est. duration</span>
          <span className="font-medium text-gray-900">{durationHours.toFixed(1)} h</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Stop order</span>
          <span className={`font-medium ${reordered ? "text-amber-600" : "text-gray-900"}`}>
            {reordered ? "Custom order" : "Default (pickups → deliveries)"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-500">Per-trip loads</span>
          <span className="font-medium text-gray-900">
            {trips
              .map((t) => {
                const w = loads[t.trip_id]?.weightKg;
                return w ? `${t.trip_id}: ${Number(w).toLocaleString()} kg` : t.trip_id;
              })
              .join(" · ")}
          </span>
        </div>
      </div>
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-gray-200 rounded-xl p-3">
      <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-1">{label}</div>
      <div className="text-lg font-semibold text-gray-900">{value}</div>
    </div>
  );
}