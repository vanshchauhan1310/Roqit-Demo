import { Card } from "@/components/common/Card";
import { Trip } from "@/types/trip";

interface DriverIntelligenceTabProps {
  trip: Trip;
}

export function DriverIntelligenceTab({ trip }: DriverIntelligenceTabProps) {
  return (
    <Card title="Driver Intelligence">
      <p className="text-sm text-gray-500">
        Driver hours, risk score, and behavior trends for driver {trip.driver_id ?? "—"} will render here.
      </p>
    </Card>
  );
}
