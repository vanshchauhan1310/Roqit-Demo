import { Card } from "@/components/common/Card";
import { Trip } from "@/types/trip";

interface ReportingKpiTabProps {
  trip: Trip;
}

export function ReportingKpiTab({ trip }: ReportingKpiTabProps) {
  return (
    <Card title="Reporting & KPI">
      <p className="text-sm text-gray-500">
        On-time performance, cost, and KPI charts for trip {trip.trip_id.slice(0, 8)} will render here.
      </p>
    </Card>
  );
}
