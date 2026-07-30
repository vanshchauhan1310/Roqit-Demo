import { useState } from "react";
import { KpiCards } from "@/components/trip/KpiCards";
import { TripsToolbar } from "@/components/trip/TripsToolbar";
import { TripsTable } from "@/components/trip/TripsTable";
import { TripsPagination } from "@/components/trip/TripsPagination";
import { CreateTripModal } from "@/components/trip/CreateTripModal";
import { CreateRouteModal } from "@/components/trip/CreateRouteModal";
import { IconPlus, IconRoute } from "@/components/common/icons";
import { useTrips, TRIPS_PAGE_SIZE } from "@/hooks/useTrips";
import { useTripFilterOptions } from "@/hooks/useTripFilterOptions";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import type { TripFilters } from "@/types/trip";

export function TripsPage() {
  const [createTripOpen, setCreateTripOpen] = useState(false);
  const [createRouteOpen, setCreateRouteOpen] = useState(false);
  const [page, setPage] = useState(1);

  const [search, setSearch] = useState("");
  const [pickupDate, setPickupDate] = useState("");
  const [status, setStatus] = useState("");
  const [driver, setDriver] = useState("");

  const debouncedSearch = useDebouncedValue(search);

  const filters: TripFilters = {
    search: debouncedSearch || undefined,
    status: status || undefined,
    driver: driver || undefined,
    pickupDate: pickupDate || undefined,
  };

  const { data: trips, isLoading, isError, isPlaceholderData } = useTrips(page, filters);
  const { data: filterOptions } = useTripFilterOptions();

  const updateFilter = (setter: (value: string) => void) => (value: string) => {
    setter(value);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Trips</h1>
          <p className="text-sm text-gray-500 mt-1">
            One trip, five intelligence lenses — routes, vehicles, drivers, live ops and KPIs.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
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
        onSearchChange={updateFilter(setSearch)}
        pickupDate={pickupDate}
        onPickupDateChange={updateFilter(setPickupDate)}
        status={status}
        onStatusChange={updateFilter(setStatus)}
        statusOptions={filterOptions?.statuses ?? []}
        driver={driver}
        onDriverChange={updateFilter(setDriver)}
        driverOptions={filterOptions?.drivers ?? []}
      />

      {isLoading && <p className="text-sm text-gray-500">Loading trips…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load trips.</p>}

      {trips && (
        <div className={`space-y-3 ${isPlaceholderData ? "opacity-60" : ""}`}>
          {trips.length === 0 ? (
            <p className="text-sm text-gray-500">No trips match these filters.</p>
          ) : (
            <>
              <TripsTable trips={trips} />
              <TripsPagination
                page={page}
                pageSize={TRIPS_PAGE_SIZE}
                rowCount={trips.length}
                hasNextPage={trips.length === TRIPS_PAGE_SIZE}
                onPageChange={setPage}
              />
            </>
          )}
        </div>
      )}

      <CreateTripModal
        open={createTripOpen}
        onClose={() => setCreateTripOpen(false)}
        onBuildRoute={() => setCreateRouteOpen(true)}
      />
      <CreateRouteModal open={createRouteOpen} onClose={() => setCreateRouteOpen(false)} />
    </div>
  );
}
