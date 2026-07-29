import { useState } from "react";
import { useTrips } from "@/hooks/useTrips";
import { TripList } from "@/components/trip/TripList";
import { CreateTripModal } from "@/components/trip/CreateTripModal";
import { Button } from "@/components/common/Button";

export function TripsPage() {
  const { data: trips, isLoading, isError } = useTrips();
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Trips</h1>
        <Button onClick={() => setCreateOpen(true)}>+ New Trip</Button>
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading trips…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load trips.</p>}
      {trips && trips.length === 0 && <p className="text-sm text-gray-500">No trips yet.</p>}
      {trips && trips.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-x-auto">
          <TripList trips={trips} />
        </div>
      )}

      <CreateTripModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
