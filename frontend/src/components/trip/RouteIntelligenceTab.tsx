import { Card } from "@/components/common/Card";
import { Trip } from "@/types/trip";

interface RouteIntelligenceTabProps {
  trip: Trip;
}

export function RouteIntelligenceTab({ trip }: RouteIntelligenceTabProps) {
  return (
    <Card title="Route Intelligence">
      <p className="text-sm text-gray-500">
        Route map, stop sequence, and ETA predictions for trip {trip.trip_id.slice(0, 8)} will render here.
      </p>
    </Card>
  );
}
