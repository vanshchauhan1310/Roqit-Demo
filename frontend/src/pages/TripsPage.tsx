import { useMemo, useState } from "react";
import { KpiCards } from "@/components/trip/KpiCards";
import { TripsToolbar } from "@/components/trip/TripsToolbar";
import { RoutesTable } from "@/components/trip/RoutesTable";
import { CreateTripModal } from "@/components/trip/CreateTripModal";
import { CreateRouteModal } from "@/components/trip/CreateRouteModal";
import { CreateFleetRouteModal } from "@/components/trip/CreateFleetRouteModal";
import { IconPlus, IconRoute } from "@/components/common/icons";
import { useRoutes } from "@/hooks/useRoutes";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { Route } from "@/types/route";

function routeMatches(route: Route, search: string, status: string, driver: string, pickupDate: string): boolean {
  const q = search.toLowerCase();
  if (status && route.status?.toLowerCase() !== status.toLowerCase()) return false;
  if (driver && route.driver_id !== driver) return false;
  if (pickupDate && route.pickup_time) {
    const day = new Date(route.pickup_time).toISOString().slice(0, 10);
    if (day !== pickupDate) return false;
  }
  if (q) {
    const haystack = [
      route.name,
      route.route_id,
      route.driver_id,
      route.vehicle_id,
      ...route.stops.map((s) => s.trip_id),
      ...route.stops.map((s) => s.address),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(q)) return false;
  }
  return true;
}

export function TripsPage() {
  const [createTripOpen, setCreateTripOpen] = useState(false);
  const [createRouteOpen, setCreateRouteOpen] = useState(false);
  const [planFleetOpen, setPlanFleetOpen] = useState(false);

  const [search, setSearch] = useState("");
  const [pickupDate, setPickupDate] = useState("");
  const [status, setStatus] = useState("");
  const [driver, setDriver] = useState("");

  const debouncedSearch = useDebouncedValue(search);

  const { data: routes, isLoading, isError } = useRoutes();

  const filteredRoutes = useMemo(() => {
    const all = routes ?? [];
    if (!debouncedSearch && !status && !driver && !pickupDate) return all;
    return all.filter((r) => routeMatches(r, debouncedSearch, status, driver, pickupDate));
  }, [routes, debouncedSearch, status, driver, pickupDate]);

  const statusOptions = useMemo(
    () => Array.from(new Set((routes ?? []).map((r) => r.status).filter((s): s is string => Boolean(s)))).sort(),
    [routes],
  );

  const driverOptions = useMemo(
    () => Array.from(new Set((routes ?? []).map((r) => r.driver_id).filter((d): d is string => Boolean(d)))).sort(),
    [routes],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Trips</h1>
          <p className="text-sm text-gray-500 mt-1">
            Grouped trips as dispatched routes — driver, vehicle, pickup time and stop sequence.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={() => setPlanFleetOpen(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <IconRoute />
            Plan Fleet Routes
          </button>
          <button
            onClick={() => setCreateRouteOpen(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <IconRoute />
            Create Route
          </button>
          <button
            onClick={() => setCreateTripOpen(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-teal-600 text-white text-sm font-medium hover:bg-teal-700"
          >
            <IconPlus />
            Create Trip
          </button>
        </div>
      </div>

      <KpiCards />
      <TripsToolbar
        search={search}
        onSearchChange={setSearch}
        pickupDate={pickupDate}
        onPickupDateChange={setPickupDate}
        status={status}
        onStatusChange={setStatus}
        statusOptions={statusOptions}
        driver={driver}
        onDriverChange={setDriver}
        driverOptions={driverOptions}
      />

      {isLoading && <p className="text-sm text-gray-500">Loading routes…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load routes.</p>}

      {routes && (
        <div className="space-y-3">
          {filteredRoutes.length === 0 ? (
            <p className="text-sm text-gray-500">No routes match these filters.</p>
          ) : (
            <RoutesTable routes={filteredRoutes} />
          )}
        </div>
      )}

      <CreateTripModal open={createTripOpen} onClose={() => setCreateTripOpen(false)} />
      <CreateRouteModal open={createRouteOpen} onClose={() => setCreateRouteOpen(false)} />
      <CreateFleetRouteModal open={planFleetOpen} onClose={() => setPlanFleetOpen(false)} />
    </div>
  );
}
