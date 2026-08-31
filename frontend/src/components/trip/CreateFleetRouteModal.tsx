import { useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createFleetPlanRoutes, optimizeFleet } from "@/api/routes";
import { useUnassignedTrips } from "@/hooks/useUnassignedTrips";
import { useTrips } from "@/hooks/useTrips";
import { useDriverRoster } from "@/hooks/useDriverRoster";
import { useVehicleRoster } from "@/hooks/useVehicleRoster";
import { useRoadRoutes } from "@/hooks/useRoadRoutes";
import { FleetRouteMap, routeColor, type FleetMapRoute } from "./FleetRouteMap";
import type { Trip } from "@/types/trip";
import type { DriverRosterItem, VehicleRosterItem } from "@/types/roster";
import type { OptimizeStopInput } from "@/types/optimize";
import type { FleetOptimizeStatus, FleetRouteMetrics, OptimizeFleetResult } from "@/types/fleet";
import { IconAlertTriangle, IconCheck, IconFuel, IconX } from "@/components/common/icons";

interface CreateFleetRouteModalProps {
  open: boolean;
  onClose: () => void;
}

const STEP_LABELS = ["Trips & Load", "Fleet", "Optimize", "Review"];
const LAST_STEP = STEP_LABELS.length - 1;
const DEFAULT_MAX_ROUTE_DURATION_SECONDS = 12 * 60 * 60;

interface DispatchJob {
  dispatchId: string;
  parentTripId: string;
  trip: Trip;
  weightKg: number | null;
  partNumber: number;
  partCount: number;
  allowedVehicleIds?: string[];
}

interface FleetPlanCandidate {
  result: OptimizeFleetResult;
  dispatchJobs: DispatchJob[];
}

/** Try a full consignment first. Only when no selected truck can carry it on
 * its own do we create reconciled, capacity-safe dispatch parts. */
function buildDispatchJobs(
  trips: Trip[],
  vehicles: VehicleRosterItem[],
): DispatchJob[] {
  return trips.flatMap((trip) => {
    const weightKg = trip.load_weight_kg;
    const eligible = vehicles
      .filter((vehicle) => (vehicle.load_capacity_kg ?? 0) > 0)
      .sort((a, b) => (b.load_capacity_kg ?? 0) - (a.load_capacity_kg ?? 0));
    const largestCapacityKg = eligible[0]?.load_capacity_kg ?? 0;
    const wholeTrip: DispatchJob = {
      dispatchId: trip.trip_id,
      parentTripId: trip.trip_id,
      trip,
      weightKg,
      partNumber: 1,
      partCount: 1,
    };
    // A normal, whole-trip assignment is always preferred. Unknown weights
    // are left untouched so the backend can return its required-weight result.
    if (weightKg == null || weightKg <= 0 || weightKg <= largestCapacityKg) return [wholeTrip];

    const splitVehicles: VehicleRosterItem[] = [];
    let combinedCapacityKg = 0;
    for (const vehicle of eligible) {
      splitVehicles.push(vehicle);
      combinedCapacityKg += vehicle.load_capacity_kg ?? 0;
      if (combinedCapacityKg >= weightKg) break;
    }
    // Even the combined selected fleet cannot carry it: preserve the original
    // job so the optimizer reports a clear no-feasible-assignment diagnostic.
    if (combinedCapacityKg < weightKg) return [wholeTrip];

    let remainingWeightKg = weightKg;
    let remainingCapacityKg = combinedCapacityKg;
    return splitVehicles.map((vehicle, index) => {
      const capacityKg = vehicle.load_capacity_kg ?? 0;
      const minimumForRemainingVehicles = Math.max(0, remainingWeightKg - (remainingCapacityKg - capacityKg));
      const assignedWeightKg = index === splitVehicles.length - 1
        ? remainingWeightKg
        : Math.min(capacityKg, Math.max(minimumForRemainingVehicles, Math.round(remainingWeightKg * capacityKg / remainingCapacityKg)));
      remainingWeightKg -= assignedWeightKg;
      remainingCapacityKg -= capacityKg;
      return {
        dispatchId: `${trip.trip_id} (part ${index + 1}/${splitVehicles.length})`,
        parentTripId: trip.trip_id,
        trip,
        weightKg: assignedWeightKg,
        partNumber: index + 1,
        partCount: splitVehicles.length,
        allowedVehicleIds: [vehicle.vehicle_id],
      };
    });
  });
}

/** The optimizer evaluates whole loads first; this candidate contains split
 * parts only where the selected fleet has no single-truck fit. */
function buildDispatchJobCandidates(trips: Trip[], vehicles: VehicleRosterItem[]): DispatchJob[][] {
  return [buildDispatchJobs(trips, vehicles)];
}

/** Weight is the dispatcher's primary decision input, so it must be visible and
 *  distinguishable at selection time. `null` means nobody has weighed this cargo;
 *  `0` is a real recorded empty load. Collapsing the two is what lets an
 *  over-capacity route pass a capacity check silently. */
function weightLabel(trip: Trip): { text: string; unknown: boolean } {
  if (trip.load_weight_kg == null) return { text: "Weight not recorded", unknown: true };
  return { text: `${trip.load_weight_kg.toLocaleString()} kg`, unknown: false };
}

function tripPlaces(trip: Trip): string {
  return `${trip.origin ?? "Unknown pickup"} → ${trip.destination ?? "Unknown destination"}`;
}

function fmtMoney(value: number): string {
  return `₹${Math.round(value).toLocaleString()}`;
}

/** Never render a duration proxy with a currency symbol. */
function costLabel(metrics: FleetRouteMetrics): string {
  return metrics.cost_is_monetary
    ? fmtMoney(metrics.total_cost)
    : `Score ${Math.round(metrics.total_cost).toLocaleString()}`;
}

const STATUS_COPY: Record<FleetOptimizeStatus, { title: string; tone: "ok" | "warn" | "error" }> = {
  SUCCESS: { title: "Every trip assigned", tone: "ok" },
  PARTIAL: { title: "Some trips couldn't be assigned", tone: "warn" },
  NO_FEASIBLE_SOLUTION: { title: "No feasible fleet assignment", tone: "error" },
  NO_FEASIBLE_ASSIGNMENT: { title: "No feasible fleet assignment", tone: "error" },
  MISSING_REQUIRED_DATA: { title: "Missing verified weight", tone: "error" },
  MISSING_COST_DATA: { title: "Missing cost configuration", tone: "error" },
  MISSING_HUB_DATA: { title: "Missing hub configuration", tone: "error" },
  DRIVER_UNAVAILABLE: { title: "Selected driver is unavailable", tone: "error" },
  VEHICLE_UNAVAILABLE: { title: "Selected vehicle is unavailable", tone: "error" },
  CAPACITY_VIOLATION: { title: "Vehicle capacity constraint failed", tone: "error" },
  PICKUP_DROP_VIOLATION: { title: "Pickup and delivery sequence is invalid", tone: "error" },
  ROUTE_DURATION_VIOLATION: { title: "Route exceeds the maximum duration", tone: "error" },
};

export function CreateFleetRouteModal({ open, onClose }: CreateFleetRouteModalProps) {
  const [step, setStep] = useState(0);
  const [selectedTripIds, setSelectedTripIds] = useState<string[]>([]);
  const [selectedVehicleIds, setSelectedVehicleIds] = useState<string[]>([]);
  const [driverByVehicle, setDriverByVehicle] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();

  const { data: trips, isLoading: tripsLoading } = useTrips(1, {});
  const { data: unassignedTrips } = useUnassignedTrips();
  const { data: drivers, isLoading: driversLoading } = useDriverRoster();
  const { data: vehicles, isLoading: vehiclesLoading } = useVehicleRoster();

  const unassignedTripIds = useMemo(
    () => new Set((unassignedTrips ?? []).map((t) => t.trip_id)),
    [unassignedTrips],
  );
  const tripsById = useMemo(() => new Map((trips ?? []).map((t) => [t.trip_id, t])), [trips]);

  const selectedTrips = selectedTripIds
    .map((id) => tripsById.get(id))
    .filter((t): t is Trip => Boolean(t));
  const selectedVehicles = (vehicles ?? []).filter((v) => selectedVehicleIds.includes(v.vehicle_id));
  const allSelectedVehiclesHaveDrivers = selectedVehicleIds.length > 0
    && selectedVehicleIds.every((vehicleId) => Boolean(driverByVehicle[vehicleId]));

  // Advisory only — the authoritative capacity check is per stop, inside the
  // solver, against each vehicle's actual assigned sequence.
  const maxFleetCapacity = selectedVehicles.reduce(
    (max, v) => Math.max(max, v.load_capacity_kg ?? 0),
    0,
  );
  const unweighedCount = selectedTrips.filter((t) => t.load_weight_kg == null).length;
  const dispatchJobCandidates = useMemo(
    () => buildDispatchJobCandidates(selectedTrips, selectedVehicles),
    [selectedTrips, selectedVehicles],
  );
  const defaultDispatchJobs = useMemo(
    () => buildDispatchJobs(selectedTrips, selectedVehicles),
    [selectedTrips, selectedVehicles],
  );
  const optimizeMutation = useMutation({
    mutationFn: async (): Promise<FleetPlanCandidate> => {
      const plans = await Promise.all(dispatchJobCandidates.map(async (candidateJobs) => {
        const stops: OptimizeStopInput[] = candidateJobs.flatMap((job) => [
        {
          key: `${job.dispatchId}:pickup`,
          latitude: job.trip.gps_start_lat ?? 0,
          longitude: job.trip.gps_start_lon ?? 0,
          trip_id: job.dispatchId,
          stop_type: "pickup" as const,
          load_weight_kg: job.weightKg,
          assigned_weight_kg: job.weightKg,
          allowed_vehicle_ids: job.allowedVehicleIds,
          allow_split_loads: job.partCount > 1,
          ...(job.partCount > 1 ? {
            parent_trip_id: job.parentTripId,
            original_load_weight_kg: job.trip.load_weight_kg,
          } : {}),
        },
        {
          key: `${job.dispatchId}:delivery`,
          latitude: job.trip.gps_end_lat ?? 0,
          longitude: job.trip.gps_end_lon ?? 0,
          trip_id: job.dispatchId,
          stop_type: "delivery" as const,
          load_weight_kg: null,
        },
      ]);
        const result = await optimizeFleet({
          stops,
          vehicles: selectedVehicleIds.map((vehicle_id) => ({
            vehicle_id,
            driver_id: driverByVehicle[vehicle_id] ?? null,
          })),
          // Fleet plans are depot-to-depot plans: reject a selection that has
          // no configured start/end hub instead of comparing open routes.
          require_hub_routing: true,
          // Review displays a currency total, so every selected vehicle and
          // driver must have a real cost configuration.
          require_monetary_cost: true,
          max_route_duration_seconds: DEFAULT_MAX_ROUTE_DURATION_SECONDS,
        });
        const overlongRoute = result.routes.find(
          (route) => route.order.length > 0
            && route.metrics.duration_seconds > DEFAULT_MAX_ROUTE_DURATION_SECONDS,
        );
        if (overlongRoute) {
          throw new Error(
            `Optimizer returned an infeasible route for ${overlongRoute.vehicle_id}: `
            + `it exceeds the 12-hour Hub-to-Hub limit. Restart the backend and ML services.`,
          );
        }
        return { result, dispatchJobs: candidateJobs };
      }));
      const completePlans = plans.filter((plan) => plan.result.unassigned_trip_ids.length === 0);
      const comparable = completePlans.length ? completePlans : plans;
      return comparable.reduce((best, candidate) =>
        candidate.result.totals.total_cost < best.result.totals.total_cost ? candidate : best,
      );
    },
    onSuccess: () => setStep(LAST_STEP),
  });

  const dispatchJobs = optimizeMutation.data?.dispatchJobs ?? defaultDispatchJobs;
  const splitJobCount = dispatchJobs.length - selectedTrips.length;
  const dispatchJobsById = useMemo(
    () => new Map(dispatchJobs.map((job) => [job.dispatchId, job])),
    [dispatchJobs],
  );
  const result = optimizeMutation.data?.result ?? null;
  const hasSplitLoads = dispatchJobs.some((job) => job.partCount > 1);
  const canSavePlan = Boolean(
    result
      && result.status === "SUCCESS"
      && result.unassigned_trip_ids.length === 0
      && result.routes.some((route) => route.order.length > 0)
      && result.routes.filter((route) => route.order.length > 0).every((route) => Boolean(route.driver_id))
      && !hasSplitLoads,
  );
  const savePlanMutation = useMutation({
    mutationFn: () => {
      if (!result) throw new Error("Optimize the fleet before adding routes.");
      return createFleetPlanRoutes({
        pickup_time: new Date().toISOString(),
        routes: result.routes
          .filter((route) => route.order.length > 0)
          .map((route) => ({
            vehicle_id: route.vehicle_id,
            driver_id: route.driver_id,
            name: `Fleet route - ${route.vehicle_id}`,
            stops: route.order.map((key) => {
              const separator = key.lastIndexOf(":");
              const job = dispatchJobsById.get(key.slice(0, separator));
              if (!job) throw new Error("A planned stop could not be matched to its trip.");
              return { trip_id: job.parentTripId, stop_type: key.slice(separator + 1) as "pickup" | "delivery" };
            }),
          })),
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["routes"] }),
        queryClient.invalidateQueries({ queryKey: ["trips"] }),
        queryClient.invalidateQueries({ queryKey: ["unassigned-trips"] }),
        queryClient.invalidateQueries({ queryKey: ["vehicle-roster"] }),
      ]);
      resetAndClose();
    },
  });

  const mapRoutesWithoutGeometry: FleetMapRoute[] = useMemo(() => {
    if (!result) return [];
    return result.routes
      .filter((r) => r.order.length > 0)
      .map((route, i) => ({
        vehicleId: route.vehicle_id,
        color: routeColor(i),
        stops: route.order
          .map((key, seq) => {
            const separator = key.lastIndexOf(":");
            const tripId = key.slice(0, separator);
            const stopType = key.slice(separator + 1) as "pickup" | "delivery";
            const job = dispatchJobsById.get(tripId);
            const trip = job?.trip;
            const lat = stopType === "pickup" ? trip?.gps_start_lat : trip?.gps_end_lat;
            const lng = stopType === "pickup" ? trip?.gps_start_lon : trip?.gps_end_lon;
            if (lat == null || lng == null) return null;
            return {
              key,
              lat,
              lng,
              label: `${stopType === "pickup" ? "Pickup" : "Delivery"} · ${stopType === "pickup" ? trip?.origin ?? "Unknown pickup" : trip?.destination ?? "Unknown destination"}`,
              sequence: seq + 1,
              stopType,
            };
          })
          .filter((s): s is NonNullable<typeof s> => s !== null),
        legs: [],
      }));
  }, [result, dispatchJobsById]);

  const roadRoutes = useRoadRoutes(
    mapRoutesWithoutGeometry.flatMap((route) =>
      route.stops.slice(1).map((stop, index) => ({
        key: `${route.vehicleId}:${index}`,
        positions: [route.stops[index], stop].map((s) => [s.lat, s.lng] as [number, number]),
      })),
    ),
  );
  const mapRoutes = useMemo(
    () => mapRoutesWithoutGeometry.map((route) => {
      const cargoOnBoard = new Set<string>();
      const legs = route.stops.slice(1).map((stop, index) => {
        const departure = route.stops[index];
        if (departure.stopType === "pickup") cargoOnBoard.add(departure.key.slice(0, departure.key.lastIndexOf(":")));
        else cargoOnBoard.delete(departure.key.slice(0, departure.key.lastIndexOf(":")));
        return {
          // Route each leg independently so loaded and empty repositioning
          // travel are visible rather than being merged into one line.
          positions: roadRoutes.geometryByKey.get(`${route.vehicleId}:${index}`)
            ?? [[departure.lat, departure.lng], [stop.lat, stop.lng]],
          carryingCargo: cargoOnBoard.size > 0,
        };
      });
      return { ...route, legs };
    }),
    [mapRoutesWithoutGeometry, roadRoutes.geometryByKey],
  );

  if (!open) return null;

  const resetAndClose = () => {
    setStep(0);
    setSelectedTripIds([]);
    setSelectedVehicleIds([]);
    setDriverByVehicle({});
    optimizeMutation.reset();
    onClose();
  };

  const toggleTrip = (tripId: string) => {
    const selected = selectedTripIds.includes(tripId);
    if (!selected && !unassignedTripIds.has(tripId)) return; // already on a route
    setSelectedTripIds((prev) => (selected ? prev.filter((id) => id !== tripId) : [...prev, tripId]));
    optimizeMutation.reset();
  };

  const toggleVehicle = (vehicleId: string) => {
    const selected = selectedVehicleIds.includes(vehicleId);
    setSelectedVehicleIds((prev) => selected ? prev.filter((id) => id !== vehicleId) : [...prev, vehicleId]);
    if (selected) {
      // Releasing a vehicle also releases its driver for another selection.
      setDriverByVehicle((assignments) => {
        const { [vehicleId]: _releasedDriver, ...remaining } = assignments;
        return remaining;
      });
    }
    optimizeMutation.reset();
  };

  const canContinue = (): boolean => {
    if (step === 0) return selectedTripIds.length >= 1;
    if (step === 1) return allSelectedVehiclesHaveDrivers;
    if (step === 2) return result != null;
    return false;
  };

  // Business outcomes arrive as `status` on a 200 and are rendered separately.
  // Anything that lands here is a genuine transport/system failure, and the three
  // kinds need different copy: a dispatcher can retry a timeout, but a 500 means
  // something is misconfigured and retrying won't help.
  const transportError = (() => {
    if (!optimizeMutation.isError) return null;
    const err = optimizeMutation.error;
    if (!isAxiosError(err)) return err instanceof Error ? err.message : "Something went wrong preparing the plan. Try again.";
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail; // backend gave a specific reason (e.g. 400)
    if (!err.response) return "Can't reach the server. Check your connection and try again.";
    if (err.response.status >= 500) {
      return "The optimizer hit a server error. This usually means the fleet cost/hub tables haven't been set up yet — it won't resolve by retrying.";
    }
    return "Couldn't optimize this fleet. Try again.";
  })();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-6xl max-h-[92vh] flex flex-col overflow-hidden">
        <div className="flex items-start justify-between px-6 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Plan Fleet Routes</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Pick the work and the fleet — the optimizer decides which vehicle takes which trip, and in what order.
            </p>
          </div>
          <button onClick={resetAndClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            <IconX />
          </button>
        </div>

        <div className="px-6 pt-5">
          <StepIndicator current={step} />
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {step === 0 && (
            <TripsLoadStep
              trips={trips ?? []}
              isLoading={tripsLoading}
              selectedTripIds={selectedTripIds}
              unassignedTripIds={unassignedTripIds}
              onToggleTrip={toggleTrip}
            />
          )}
          {step === 1 && (
            <FleetStep
              vehicles={vehicles ?? []}
              drivers={drivers ?? []}
              vehiclesLoading={vehiclesLoading}
              driversLoading={driversLoading}
              selectedVehicleIds={selectedVehicleIds}
              onToggleVehicle={toggleVehicle}
              driverByVehicle={driverByVehicle}
              onAssignDriver={(vehicleId, driverId) => {
                setDriverByVehicle((prev) => {
                  const selectedElsewhere = Object.entries(prev).some(
                    ([otherVehicleId, assignedDriverId]) => otherVehicleId !== vehicleId && assignedDriverId === driverId,
                  );
                  return selectedElsewhere ? prev : { ...prev, [vehicleId]: driverId };
                });
                optimizeMutation.reset();
              }}
            />
          )}
          {step === 2 && (
            <OptimizeStep
              tripCount={selectedTrips.length}
              dispatchJobCount={dispatchJobs.length}
              splitJobCount={splitJobCount}
              vehicleCount={selectedVehicleIds.length}
              unweighedCount={unweighedCount}
              maxFleetCapacity={maxFleetCapacity}
              isOptimizing={optimizeMutation.isPending}
              onOptimize={() => optimizeMutation.mutate()}
              transportError={transportError}
              result={result}
            />
          )}
          {step === 3 && result && (
            <ReviewStep
              result={result}
              mapRoutes={mapRoutes}
              routesLoading={roadRoutes.isLoading}
              dispatchJobsById={dispatchJobsById}
              vehicleCapacityById={new Map(selectedVehicles.map((vehicle) => [vehicle.vehicle_id, vehicle.load_capacity_kg]))}
            />
          )}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100">
          <button
            onClick={() => setStep((s) => Math.max(s - 1, 0))}
            disabled={step === 0}
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 disabled:text-gray-300 disabled:cursor-not-allowed"
          >
            Back
          </button>

          {step < 2 && (
            <button
              onClick={() => setStep((s) => s + 1)}
              disabled={!canContinue()}
              className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Continue
            </button>
          )}
          {step === 2 && (
            <button
              onClick={() => (result ? setStep(LAST_STEP) : optimizeMutation.mutate())}
              disabled={optimizeMutation.isPending || !allSelectedVehiclesHaveDrivers}
              className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50"
            >
              {optimizeMutation.isPending ? "Optimizing…" : result ? "Review plan" : "Optimize fleet"}
            </button>
          )}
          {step === LAST_STEP && (
            <div className="ml-auto flex items-center gap-3">
            <span className="hidden">
              Dispatching this plan isn't wired up yet — review only.
            </span>
              {hasSplitLoads && <span className="text-xs text-amber-700">Split-load plans are review-only until shipment parts can be stored.</span>}
              {savePlanMutation.isError && <span className="text-xs text-red-600">Couldn&apos;t add routes. Please try again.</span>}
              <button
                onClick={() => savePlanMutation.mutate()}
                disabled={!canSavePlan || savePlanMutation.isPending}
                className="px-5 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {savePlanMutation.isPending ? "Adding routes…" : "Add routes"}
              </button>
            </div>
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

interface TripsLoadStepProps {
  trips: Trip[];
  isLoading: boolean;
  selectedTripIds: string[];
  unassignedTripIds: Set<string>;
  onToggleTrip: (tripId: string) => void;
}

function TripsLoadStep({ trips, isLoading, selectedTripIds, unassignedTripIds, onToggleTrip }: TripsLoadStepProps) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-semibold text-gray-900 mb-1">Select trips to dispatch</label>
        <p className="text-xs text-gray-400">
          Stored weights are shown as recorded — no re-entry needed. Trips already on a route are shown but can't be
          selected. Nothing is filtered by vehicle here; the fleet is chosen next.
        </p>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading trips…</p>}
      {!isLoading && trips.length === 0 && (
        <p className="text-sm text-gray-400">No trips available — create a trip first.</p>
      )}

      <div className="border border-gray-200 rounded-xl overflow-hidden">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              {["", "Trip", "Pickup → Drop", "Weight", "Status"].map((h) => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {trips.map((trip) => {
              const selected = selectedTripIds.includes(trip.trip_id);
              const alreadyRouted = !unassignedTripIds.has(trip.trip_id) && !selected;
              const weight = weightLabel(trip);
              return (
                <tr
                  key={trip.trip_id}
                  onClick={() => !alreadyRouted && onToggleTrip(trip.trip_id)}
                  className={`${
                    alreadyRouted ? "bg-gray-50 opacity-60 cursor-not-allowed" : "cursor-pointer hover:bg-gray-50"
                  } ${selected ? "bg-teal-50" : ""}`}
                >
                  <td className="px-4 py-2.5">
                    <span
                      className={`w-5 h-5 rounded border flex items-center justify-center ${
                        selected ? "bg-teal-600 border-teal-600 text-white" : "border-gray-300 text-transparent"
                      }`}
                    >
                      <IconCheck />
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-medium text-gray-900 whitespace-nowrap">{trip.trip_id}</td>
                  <td className="px-4 py-2.5 text-gray-600">
                    {trip.origin ?? "—"} → {trip.destination ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    {weight.unknown ? (
                      <span className="inline-flex items-center gap-1 text-amber-700">
                        <IconAlertTriangle />
                        {weight.text}
                      </span>
                    ) : (
                      <span className="text-gray-900 font-medium">{weight.text}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    {alreadyRouted ? (
                      <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium">
                        Already assigned
                      </span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-medium">
                        Available
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface FleetStepProps {
  vehicles: VehicleRosterItem[];
  drivers: DriverRosterItem[];
  vehiclesLoading: boolean;
  driversLoading: boolean;
  selectedVehicleIds: string[];
  onToggleVehicle: (id: string) => void;
  driverByVehicle: Record<string, string>;
  onAssignDriver: (vehicleId: string, driverId: string) => void;
}

function FleetStep({
  vehicles,
  drivers,
  vehiclesLoading,
  driversLoading,
  selectedVehicleIds,
  onToggleVehicle,
  driverByVehicle,
  onAssignDriver,
}: FleetStepProps) {
  const unavailableDriverStatuses = new Set(["off-duty", "inactive", "unavailable", "suspended"]);
  const availableDrivers = drivers.filter(
    (driver) => !driver.is_on_trip
      && driver.assignment_status !== "assigned"
      && !unavailableDriverStatuses.has((driver.status ?? "").toLowerCase()),
  );
  const selectedWithoutDriver = selectedVehicleIds.filter((vehicleId) => !driverByVehicle[vehicleId]);
  const hubOrder = ["Hyderabad", "Delhi", "Chennai"];
  const fleetVehicles = [...vehicles].sort((a, b) => {
    const aHub = a.hub_name ?? "Unassigned hub";
    const bHub = b.hub_name ?? "Unassigned hub";
    const aPosition = hubOrder.findIndex((city) => aHub.includes(city));
    const bPosition = hubOrder.findIndex((city) => bHub.includes(city));
    return (aPosition === -1 ? hubOrder.length : aPosition) - (bPosition === -1 ? hubOrder.length : bPosition)
      || aHub.localeCompare(bHub)
      || a.vehicle_id.localeCompare(b.vehicle_id);
  });
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-semibold text-gray-900 mb-1">Choose the available fleet</label>
        <p className="text-xs text-gray-400">
          Offer as many vehicles as you're willing to dispatch — the optimizer decides how many it actually needs and
          leaves the rest idle. Pair an available driver with every selected vehicle before optimizing.
        </p>
      </div>

      {selectedWithoutDriver.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Assign an available driver to: {selectedWithoutDriver.join(", ")}.
        </div>
      )}

      {vehiclesLoading && <p className="text-sm text-gray-400">Loading vehicles…</p>}
      {!vehiclesLoading && vehicles.length === 0 && <p className="text-sm text-gray-400">No vehicles found.</p>}

      <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
        {fleetVehicles.map((vehicle, index) => {
          const selected = selectedVehicleIds.includes(vehicle.vehicle_id);
          const isAssigned = vehicle.assignment_status === "assigned";
          const isUnavailable = vehicle.assignment_status === "unavailable" || vehicle.is_on_trip;
          const unavailable = isAssigned || isUnavailable;
          const hubName = vehicle.hub_name ?? "Unassigned hub";
          const previousHubName = index > 0 ? fleetVehicles[index - 1].hub_name ?? "Unassigned hub" : null;
          
          return (
            <div key={vehicle.vehicle_id}>
              {hubName !== previousHubName && (
                <div className="sticky top-0 z-10 -mx-1 mb-2 px-2 py-1.5 bg-white border-b border-gray-100 text-xs font-semibold tracking-wide text-gray-600 uppercase">
                  {hubName}
                </div>
              )}
              <div className={`rounded-lg border transition-colors ${
                selected
                  ? "border-teal-500 bg-teal-50"
                  : unavailable
                    ? "border-gray-100 bg-gray-50 opacity-60"
                    : "border-gray-200"
              }`}
            >
              <button
                type="button"
                onClick={() => !unavailable && onToggleVehicle(vehicle.vehicle_id)}
                disabled={unavailable}
                className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left disabled:cursor-not-allowed"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`w-5 h-5 shrink-0 rounded border flex items-center justify-center ${
                      selected ? "bg-teal-600 border-teal-600 text-white" : "border-gray-300 text-transparent"
                    }`}
                  >
                    <IconCheck />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="text-sm font-medium text-gray-900 truncate">
                        {vehicle.vehicle_id} · {vehicle.vehicle_type ?? "—"}
                      </div>
                      {isAssigned && (
                        <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-xs font-medium flex-shrink-0">
                          Assigned
                        </span>
                      )}
                      {isUnavailable && !isAssigned && (
                        <span className="px-2 py-0.5 rounded-full bg-red-100 text-red-800 text-xs font-medium flex-shrink-0">
                          Unavailable
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {vehicle.load_capacity_kg != null
                        ? `${vehicle.load_capacity_kg.toLocaleString()} kg capacity`
                        : "Capacity unknown"}
                      {vehicle.fuel_type ? ` · ${vehicle.fuel_type}` : ""}
                      {vehicle.current_route_name && (
                        <span className="ml-2 text-amber-700">→ {vehicle.current_route_name}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {unavailable && !isAssigned && (
                    <span className="px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 text-xs font-medium">
                      In Use
                    </span>
                  )}
                  {vehicle.avg_kmpl_rated != null && (
                    <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-sky-50 text-sky-700 text-xs font-medium whitespace-nowrap">
                      <IconFuel />
                      {vehicle.avg_kmpl_rated} km/l
                    </span>
                  )}
                </div>
              </button>

              {selected && (
                <div className="px-4 pb-3 pt-1 border-t border-teal-100">
                  <label className="block text-xs text-gray-600 mb-1">Driver for {vehicle.vehicle_id}</label>
                  {driversLoading ? (
                    <p className="text-xs text-gray-400">Loading drivers…</p>
                  ) : (
                    <select
                      value={driverByVehicle[vehicle.vehicle_id] ?? ""}
                      onChange={(e) => onAssignDriver(vehicle.vehicle_id, e.target.value)}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white"
                    >
                      <option value="" disabled>Select an available driver</option>
                      {availableDrivers.map((d) => {
                        const driverAssigned = Object.entries(driverByVehicle).some(
                          ([assignedVehicleId, assignedDriverId]) =>
                            assignedVehicleId !== vehicle.vehicle_id && assignedDriverId === d.driver_id,
                        );
                        return (
                          <option key={d.driver_id} value={d.driver_id} disabled={driverAssigned}>
                            {d.driver_name ?? d.driver_id}
                            {d.rating != null ? ` · ★ ${d.rating}` : ""}
                            {driverAssigned ? " (Selected for another vehicle)" : ""}
                          </option>
                        );
                      })}
                    </select>
                  )}
                </div>
              )}
            </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface OptimizeStepProps {
  tripCount: number;
  dispatchJobCount: number;
  splitJobCount: number;
  vehicleCount: number;
  unweighedCount: number;
  maxFleetCapacity: number;
  isOptimizing: boolean;
  onOptimize: () => void;
  transportError: string | null;
  result: OptimizeFleetResult | null;
}

function OptimizeStep({
  tripCount,
  dispatchJobCount,
  splitJobCount,
  vehicleCount,
  unweighedCount,
  maxFleetCapacity,
  isOptimizing,
  onOptimize,
  transportError,
  result,
}: OptimizeStepProps) {
  const status = result ? STATUS_COPY[result.status] : null;
  const isBlocking = result != null && result.routes.length === 0;

  return (
    <div className="space-y-4 max-w-3xl">
      <div>
        <label className="block text-sm font-semibold text-gray-900 mb-1">Optimize the fleet</label>
        <p className="text-xs text-gray-400">
          Capacity is enforced at every stop against each vehicle's actual sequence, and a delivery can never precede
          its own pickup. The optimizer minimizes total fleet operating cost across distance, time, fuel and cargo
          load.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Trips" value={splitJobCount ? `${tripCount} → ${dispatchJobCount} loads` : String(tripCount)} />
        <Stat label="Vehicles offered" value={String(vehicleCount)} />
        <Stat label="Largest capacity" value={maxFleetCapacity ? `${maxFleetCapacity.toLocaleString()} kg` : "—"} />
        <Stat label="Unweighed trips" value={String(unweighedCount)} tone={unweighedCount ? "warn" : undefined} />
      </div>

      {unweighedCount > 0 && (
        <div className="px-4 py-3 rounded-lg bg-amber-50 border border-amber-100 text-sm text-amber-800">
          {unweighedCount} selected trip{unweighedCount === 1 ? " has" : "s have"} no recorded weight. Capacity can't
          be guaranteed for unweighed cargo — the optimizer will refuse a capacity-constrained plan until a weight is
          recorded.
        </div>
      )}

      {splitJobCount > 0 && (
        <div className="px-4 py-3 rounded-lg bg-sky-50 border border-sky-100 text-sm text-sky-800">
          Oversized consignments will be planned as {dispatchJobCount} dispatchable loads. Each load stays below the
          largest selected vehicle capacity; this is a planning split and does not alter the original trip record.
        </div>
      )}

      {transportError && (
        <div className="px-4 py-3 rounded-lg bg-red-50 border border-red-100 text-sm text-red-700">
          {transportError}
        </div>
      )}

      {status && isBlocking && (
        <div
          className={`px-4 py-3 rounded-lg border text-sm ${
            status.tone === "error"
              ? "bg-red-50 border-red-100 text-red-700"
              : "bg-amber-50 border-amber-100 text-amber-800"
          }`}
        >
          <div className="font-medium mb-1">{status.title}</div>
          {result?.warnings.map((w) => <div key={w}>{w}</div>)}
          {result?.warnings.length === 0 && <div>No vehicle in the selected fleet can carry these trips.</div>}
        </div>
      )}

      {!result && (
        <button
          type="button"
          onClick={onOptimize}
          disabled={isOptimizing || vehicleCount === 0}
          className="px-5 py-2.5 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 disabled:opacity-50"
        >
          {isOptimizing ? "Optimizing…" : "Optimize fleet"}
        </button>
      )}
      {result && !isBlocking && (
        <div className="px-4 py-3 rounded-lg bg-emerald-50 border border-emerald-100 text-sm text-emerald-800">
          <div className="font-medium">{status?.title}</div>
          <div className="mt-0.5">
            {result.vehicles_used} of {vehicleCount} vehicle{vehicleCount === 1 ? "" : "s"} used — continue to review
            the plan.
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "warn" }) {
  return (
    <div className={`border rounded-xl p-3 ${tone === "warn" ? "border-amber-200 bg-amber-50" : "border-gray-200"}`}>
      <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-1">{label}</div>
      <div className={`text-lg font-semibold ${tone === "warn" ? "text-amber-800" : "text-gray-900"}`}>{value}</div>
    </div>
  );
}

interface ReviewStepProps {
  result: OptimizeFleetResult;
  mapRoutes: FleetMapRoute[];
  routesLoading: boolean;
  dispatchJobsById: Map<string, DispatchJob>;
  vehicleCapacityById: Map<string, number | null>;
}

function ReviewStep({ result, mapRoutes, routesLoading, dispatchJobsById, vehicleCapacityById }: ReviewStepProps) {
  const used = result.routes.filter((r) => r.order.length > 0);
  const idle = result.routes.filter((r) => r.order.length === 0);
  const totals = result.totals;
  const unassignedStatus = STATUS_COPY[result.status];
  const tripAssignments = new Map<string, { vehicleId: string; assignedWeightKg: number | null; originalWeightKg: number | null; split: boolean; places: string }[]>();
  for (const route of used) {
    for (const tripId of route.trip_ids) {
      const job = dispatchJobsById.get(tripId);
      if (!job) continue;
      const assignments = tripAssignments.get(job.parentTripId) ?? [];
      assignments.push({
        vehicleId: route.vehicle_id,
        assignedWeightKg: job.weightKg,
        originalWeightKg: job.trip.load_weight_kg,
        split: job.partCount > 1,
        places: tripPlaces(job.trip),
      });
      tripAssignments.set(job.parentTripId, assignments);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        {result.unassigned_trip_ids.length > 0 && (
          <div className="px-4 py-3 rounded-lg bg-amber-50 border border-amber-100 text-sm text-amber-800">
            <span className="font-medium">Unassigned:</span> {result.unassigned_trip_ids.join(", ")} — {unassignedStatus.title}.
            {result.warnings.map((warning) => <div key={warning} className="mt-1">{warning}</div>)}
          </div>
        )}
        {false && result.unassigned_trip_ids.length > 0 && (
          <div className="px-4 py-3 rounded-lg bg-amber-50 border border-amber-100 text-sm text-amber-800">
            <span className="font-medium">Unassigned:</span> {result.unassigned_trip_ids.join(", ")} — no vehicle in
            this fleet could carry {result.unassigned_trip_ids.length === 1 ? "it" : "them"}.
          </div>
        )}

        {tripAssignments.size > 0 && (
          <section className="rounded-xl border border-sky-100 overflow-hidden">
            <div className="px-4 py-2 bg-sky-50 text-sm font-semibold text-sky-950">Trip assignment summary</div>
            {[...tripAssignments.entries()].map(([tripId, assignments]) => (
              <div key={tripId} className="px-4 py-3 border-t border-sky-100 text-sm text-sky-900">
                <div className="font-semibold">
                  {assignments[0].places} — original trip weight: {assignments[0].originalWeightKg?.toLocaleString() ?? "Not recorded"}{assignments[0].originalWeightKg != null ? " kg" : ""}
                </div>
                <div className="mt-1 text-sky-800">
                  {assignments.map((assignment) => (
                    <div key={assignment.vehicleId}>
                      {assignment.vehicleId}: {assignment.split
                        ? `${assignment.assignedWeightKg?.toLocaleString() ?? "Unknown"} kg assigned`
                        : "assigned the full trip"}
                    </div>
                  ))}
                </div>
                {assignments[0].originalWeightKg != null && (
                  <div className="mt-1 text-xs font-medium text-sky-700">
                    Reconciled assigned weight: {assignments.reduce((sum, assignment) => sum + (assignment.assignedWeightKg ?? 0), 0).toLocaleString()} / {assignments[0].originalWeightKg.toLocaleString()} kg
                  </div>
                )}
              </div>
            ))}
          </section>
        )}

        {used.map((route, i) => {
          const m = route.metrics;
          const assignedCargoKg = route.trip_ids.reduce(
            (sum, tripId) => sum + (dispatchJobsById.get(tripId)?.weightKg ?? 0),
            0,
          );
          let cargoOnBoardKg = 0;
          const sequenceStops = route.order.map((key, sequence) => {
            const separator = key.lastIndexOf(":");
            const dispatchId = key.slice(0, separator);
            const stopType = key.slice(separator + 1) as "pickup" | "delivery";
            const job = dispatchJobsById.get(dispatchId);
            const assignedWeightKg = job?.weightKg ?? 0;
            cargoOnBoardKg += stopType === "pickup" ? assignedWeightKg : -assignedWeightKg;
            return { key, sequence, stopType, job, assignedWeightKg, cargoOnBoardKg };
          });
          return (
            <div key={route.vehicle_id} className="border border-gray-200 rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 bg-gray-50">
                <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: routeColor(i) }} />
                <span className="font-semibold text-gray-900 text-sm">{route.vehicle_id}</span>
                <span className="text-xs text-gray-500">
                  {route.driver_id ? `Driver ${route.driver_id}` : "No driver assigned"}
                </span>
                <span className="text-xs text-gray-500">
                  Max capacity: {vehicleCapacityById.get(route.vehicle_id)?.toLocaleString() ?? "Not configured"} kg
                </span>
                <span className="ml-auto text-sm font-semibold text-gray-900">{costLabel(m)}</span>
              </div>
              <div className="px-4 py-3 space-y-3">
                <div className="text-sm text-gray-700">
                  <span className="text-gray-500">Trips: </span>
                  {route.trip_ids.map((tripId) => {
                    const job = dispatchJobsById.get(tripId);
                    return job?.partCount && job.partCount > 1
                      ? `${tripPlaces(job.trip)}: ${job.weightKg?.toLocaleString()} kg assigned (part ${job.partNumber}/${job.partCount}; original ${job.trip.load_weight_kg?.toLocaleString()} kg)`
                      : job ? tripPlaces(job.trip) : tripId;
                  }).join(", ")}
                </div>
                <div className="border-t border-gray-100 pt-3">
                  <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase mb-2">
                    Pickup &amp; delivery sequence
                  </div>
                  <ol className="space-y-1.5">
                    {sequenceStops.map(({ key, sequence, stopType, job, assignedWeightKg, cargoOnBoardKg }) => {
                      const place = stopType === "pickup" ? job?.trip.origin : job?.trip.destination;
                      const tripLabel = job?.partCount && job.partCount > 1
                        ? `${tripPlaces(job.trip)} (part ${job.partNumber}/${job.partCount})`
                        : job ? tripPlaces(job.trip) : "Trip details unavailable";
                      return (
                        <li key={key} className="flex items-center gap-2 text-xs text-gray-700">
                          <span className={`w-6 h-6 rounded-full flex items-center justify-center font-semibold ${stopType === "pickup" ? "bg-teal-600 text-white" : "border-2 border-teal-600 text-teal-700"}`}>
                            {sequence + 1}
                          </span>
                          <span className={`font-medium ${stopType === "pickup" ? "text-teal-700" : "text-gray-700"}`}>
                            {stopType === "pickup" ? "Pickup" : "Drop"}
                          </span>
                          <span>{tripLabel}</span>
                          <span className="text-gray-400">—</span>
                          <span className="text-gray-500">{place ?? "Place not recorded"}</span>
                          <span className={stopType === "pickup" ? "text-teal-700 font-medium" : "text-rose-700 font-medium"}>
                            {stopType === "pickup" ? "Loaded" : "Unloaded"}: {assignedWeightKg.toLocaleString()} kg
                          </span>
                          <span className="text-gray-500">
                            {stopType === "pickup" ? "On board" : "Remaining on board"}: {Math.max(0, cargoOnBoardKg).toLocaleString()} kg
                          </span>
                        </li>
                      );
                    })}
                  </ol>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  <Metric
                    label="Peak / max load"
                    value={`${Math.round(m.peak_load_kg).toLocaleString()} / ${vehicleCapacityById.get(route.vehicle_id)?.toLocaleString() ?? "—"} kg`}
                  />
                  <Metric label="Cargo assigned" value={`${assignedCargoKg.toLocaleString()} kg`} />
                  <Metric label="Distance" value={`${(m.distance_meters / 1000).toFixed(1)} km`} />
                  <Metric label="Time" value={`${Math.round(m.duration_seconds / 60)} min`} />
                  <Metric label="Fuel" value={m.fuel_liters ? `${m.fuel_liters.toFixed(1)} L` : "—"} />
                </div>
                {m.cost_is_monetary && (
                  <div className="text-xs text-gray-500 pt-1 border-t border-gray-100">
                    Fuel {fmtMoney(m.fuel_cost)} · Driver {fmtMoney(m.driver_cost)} · Operating{" "}
                    {fmtMoney(m.operating_cost)} · Fixed {fmtMoney(m.fixed_cost)}
                  </div>
                )}
                {!m.cost_is_monetary && (
                  <div className="text-xs text-amber-700 pt-1 border-t border-gray-100">
                    Cost rates aren't fully configured for this vehicle, so this is a relative optimization score, not
                    currency.
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {idle.length > 0 && (
          <div className="px-4 py-3 rounded-lg border border-gray-200 bg-gray-50 text-sm text-gray-600">
            <span className="font-medium">Not dispatched:</span> {idle.map((r) => r.vehicle_id).join(", ")} — using{" "}
            {idle.length === 1 ? "it" : "them"} wouldn't have lowered total fleet cost.
          </div>
        )}

        <div className="border border-gray-900 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 bg-gray-900 text-white text-sm font-semibold">Total fleet</div>
          <div className="px-4 py-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <Metric label="Distance" value={`${(totals.distance_meters / 1000).toFixed(1)} km`} />
            <Metric label="Time" value={`${Math.round(totals.duration_seconds / 60)} min`} />
            <Metric label="Fuel" value={totals.fuel_liters ? `${totals.fuel_liters.toFixed(1)} L` : "—"} />
            <Metric label={totals.cost_is_monetary ? "Total cost" : "Total score"} value={costLabel(totals)} />
          </div>
          {totals.cost_is_monetary && (
            <div className="px-4 pb-3 text-xs text-gray-500">
              Fuel {fmtMoney(totals.fuel_cost)} · Driver {fmtMoney(totals.driver_cost)} · Operating{" "}
              {fmtMoney(totals.operating_cost)} · Fixed {fmtMoney(totals.fixed_cost)}
            </div>
          )}
        </div>

        {result.explanation.length > 0 && (
          <details className="border border-gray-200 rounded-xl px-4 py-3">
            <summary className="text-sm font-medium text-gray-700 cursor-pointer">Why this plan?</summary>
            <ul className="mt-2 space-y-1 text-xs text-gray-600">
              {result.explanation.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        )}

        {result.unassigned_diagnostics.length > 0 && (
          <details className="border border-red-200 rounded-xl px-4 py-3 bg-red-50">
            <summary className="text-sm font-medium text-red-700 cursor-pointer">Unassigned trips — detailed diagnostics</summary>
            <div className="mt-3 space-y-4">
              {result.unassigned_diagnostics.map((diag) => (
                <div key={diag.trip_id} className="border border-red-200 rounded-lg p-3 bg-white">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-gray-900">{diag.trip_id}</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      diag.status === "EXCEEDS_ALL_VEHICLES" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"
                    }`}>
                      {diag.primary_failure_reason ?? diag.status}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs text-gray-600 mb-2">
                    <div><span className="font-medium text-gray-900">Trip weight: </span>{diag.trip_weight_kg.toLocaleString()} kg</div>
                    <div><span className="font-medium text-gray-900">Positions tested: </span>{diag.total_positions_tested}</div>
                    <div><span className="font-medium text-gray-900">Capacity failures: </span>{diag.capacity_failures}</div>
                    <div><span className="font-medium text-gray-900">Precedence failures: </span>{diag.precedence_failures}</div>
                  </div>
                  {diag.minimum_required_capacity_kg != null && (
                    <div className="text-xs text-amber-700 mb-2">
                      Minimum peak load after insertion: {diag.minimum_required_capacity_kg.toLocaleString()} kg
                    </div>
                  )}
                  <details className="border-t border-gray-100 pt-2">
                    <summary className="text-xs font-medium text-gray-500 cursor-pointer">Per-vehicle details</summary>
                    <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
                      {diag.vehicle_diagnostics.map((vd) => (
                        <div key={vd.vehicle_id} className="text-xs text-gray-600 bg-gray-50 rounded p-2">
                          <div className="font-medium text-gray-900">{vd.vehicle_id} (cap: {vd.vehicle_capacity_kg?.toLocaleString() ?? "∞"} kg)</div>
                          <div className="grid grid-cols-2 gap-1 mt-1 text-[10px]">
                            <span>Current peak: {vd.current_peak_load_kg.toLocaleString()} kg</span>
                            <span>Remaining: {vd.static_remaining_capacity_kg?.toLocaleString() ?? "∞"} kg</span>
                            <span>Feasible insertions: {vd.feasible_insertions}</span>
                            <span>Best peak: {vd.best_peak_load_kg?.toLocaleString() ?? "N/A"} kg</span>
                            <span>Pos tested: {vd.total_pickup_positions_tested}×{vd.total_delivery_positions_tested}</span>
                            <span>Cap failures: {vd.capacity_failures}</span>
                            <span>Prec failures: {vd.precedence_failures}</span>
                            <span>Best cost: {vd.best_incremental_cost?.toFixed(1) ?? "N/A"}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      <div className="flex flex-col min-h-[380px]">
        <FleetRouteMap routes={mapRoutes} emptyLabel="No routed stops to show" />
        {routesLoading && <p className="mt-2 text-xs text-gray-500">Drawing road routes…</p>}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase">{label}</div>
      <div className="text-sm font-semibold text-gray-900 mt-0.5">{value}</div>
    </div>
  );
}
