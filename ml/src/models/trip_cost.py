# Predicts total trip cost. Trained externally - this artifact was provided
# directly, so there's no train() here.

from pathlib import Path

import joblib
import pandas as pd

from src.features.build_features import build_cost_features

MODEL_PATH = Path(__file__).resolve().parents[2] / "models_store" / "trip_cost_xgboost_v1.pkl"


def predict(payload: dict) -> float:
    """payload must contain the 10 fields in build_features.COST_FEATURE_ORDER."""
    model = joblib.load(MODEL_PATH)
    features = build_cost_features(pd.DataFrame([payload]))
    return float(model.predict(features)[0])
