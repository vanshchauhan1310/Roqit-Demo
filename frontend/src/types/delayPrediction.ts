export interface DelayPrediction {
  prediction_id: string;
  trip_id: string;
  delay_probability: number;
  is_delayed_prediction: boolean;
  model_version: string;
  features: Record<string, unknown>;
  predicted_at: string;
}

export interface ExpectedDelay {
  predicted_delay_minutes: number;
}
