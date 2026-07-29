import { Card } from "@/components/common/Card";
import { Trip } from "@/types/trip";

interface VehicleIntelligenceTabProps {
  trip: Trip;
}

export function VehicleIntelligenceTab({ trip }: VehicleIntelligenceTabProps) {
  return (
    <Card title="Vehicle Intelligence">
      <p className="text-sm text-gray-500">
        Vehicle health, fuel efficiency, and maintenance signals for vehicle {trip.vehicle_id ?? "—"} will render here.
      </p>
    </Card>
  );
}
