import { Card } from "@/components/common/Card";
import { Trip } from "@/types/trip";
import { DelayRiskCard } from "./DelayRiskCard";

interface RealTimeOpsTabProps {
  trip: Trip;
}

export function RealTimeOpsTab({ trip }: RealTimeOpsTabProps) {
  return (
    <div className="space-y-4">
      <Card title="Real-Time Operations">
        <p className="text-sm text-gray-500">
          Live GPS breadcrumbs and status updates for trip {trip.trip_id.slice(0, 8)} will render here.
        </p>
      </Card>
      <DelayRiskCard trip={trip} />
    </div>
  );
}
