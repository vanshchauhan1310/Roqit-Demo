import { useParams, Link } from "react-router-dom";
import { useTripDetail } from "@/hooks/useTripDetail";
import { TripDetailTabs } from "@/components/trip/TripDetailTabs";

export function TripDetailPage() {
  const { tripId } = useParams<{ tripId: string }>();
  const { data: trip, isLoading, isError } = useTripDetail(tripId);

  return (
    <div>
      <Link to="/trips" className="text-sm text-blue-600 hover:underline">
        ← Back to Trips
      </Link>

      {isLoading && <p className="text-sm text-gray-500 mt-4">Loading trip…</p>}
      {isError && <p className="text-sm text-red-600 mt-4">Failed to load trip.</p>}

      {trip && (
        <div className="mt-4">
          <h1 className="text-xl font-semibold text-gray-900 mb-6">
            Trip {trip.trip_id.slice(0, 8)} — {trip.origin ?? "?"} → {trip.destination ?? "?"}
          </h1>
          <TripDetailTabs trip={trip} />
        </div>
      )}
    </div>
  );
}
