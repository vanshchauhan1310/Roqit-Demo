import { isAxiosError } from "axios";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { Trip } from "@/types/trip";
import { useMlEtaPrediction } from "@/hooks/useMlEtaPrediction";

interface MlEtaCardProps {
  trip: Trip;
}

export function MlEtaCard({ trip }: MlEtaCardProps) {
  const mutation = useMlEtaPrediction(trip.trip_id);

  let errorMessage: string | null = null;
  if (mutation.error) {
    if (isAxiosError(mutation.error)) {
      const detail = mutation.error.response?.data?.detail;
      errorMessage = typeof detail === "string" ? detail : "ETA prediction failed.";
    } else {
      errorMessage = "ETA prediction failed.";
    }
  }

  const prediction = mutation.data;

  return (
    <Card title="ML ETA Prediction">
      <p className="text-sm text-gray-500 mb-3">
        Predicts expected delay (trained regression model) and adds it to the planned duration.
      </p>

      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
        {mutation.isPending ? "Predicting…" : "Run ETA Prediction"}
      </Button>

      {errorMessage && <p className="text-sm text-red-600 mt-3">{errorMessage}</p>}

      {prediction && (
        <div className="mt-4 space-y-1">
          <p className="text-sm font-medium text-gray-900">
            Predicted delivery: {new Date(prediction.predicted_delivery_time).toLocaleString()}
          </p>
          <p className="text-xs text-gray-400">
            Planned duration {prediction.planned_duration_hours.toFixed(1)}h + expected delay{" "}
            {prediction.expected_delay_minutes.toFixed(0)} min
          </p>
        </div>
      )}
    </Card>
  );
}
