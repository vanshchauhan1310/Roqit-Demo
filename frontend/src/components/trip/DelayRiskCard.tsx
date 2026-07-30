import { isAxiosError } from "axios";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { Trip } from "@/types/trip";
import { useDelayPrediction } from "@/hooks/useDelayPrediction";

interface DelayRiskCardProps {
  trip: Trip;
}

function riskBadge(probability: number): { label: string; className: string } {
  if (probability >= 0.5) return { label: "High Risk", className: "bg-red-50 text-red-600" };
  if (probability >= 0.25) return { label: "Medium Risk", className: "bg-amber-50 text-amber-600" };
  return { label: "Low Risk", className: "bg-green-50 text-green-600" };
}

export function DelayRiskCard({ trip }: DelayRiskCardProps) {
  const mutation = useDelayPrediction(trip.trip_id);

  let errorMessage: string | null = null;
  if (mutation.error) {
    if (isAxiosError(mutation.error)) {
      const detail = mutation.error.response?.data?.detail;
      errorMessage = typeof detail === "string" ? detail : "Delay prediction failed.";
    } else {
      errorMessage = "Delay prediction failed.";
    }
  }

  const prediction = mutation.data;
  const badge = prediction ? riskBadge(prediction.delay_probability) : null;

  return (
    <Card title="Delay Risk Prediction">
      <p className="text-sm text-gray-500 mb-3">
        Runs the full pipeline: fetch trip → engineer features → load model → predict → store.
      </p>

      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
        {mutation.isPending ? "Predicting…" : "Run Delay Prediction"}
      </Button>

      {errorMessage && <p className="text-sm text-red-600 mt-3">{errorMessage}</p>}

      {prediction && badge && (
        <div className="mt-4 space-y-2">
          <span className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${badge.className}`}>
            {badge.label} — {(prediction.delay_probability * 100).toFixed(1)}%
          </span>
          <p className="text-xs text-gray-400">
            Model: {prediction.model_version} · Predicted {new Date(prediction.predicted_at).toLocaleString()}
          </p>
        </div>
      )}
    </Card>
  );
}
