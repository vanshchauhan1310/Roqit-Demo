# Predicts expected delay in minutes (regression) using the same 25-field
# feature set as delay_risk.py's classifier. Trained externally - this
# artifact was provided directly, so there's no train() here.

from pathlib import Path

import joblib
import pandas as pd

from src.features.build_features import build_delay_features, load_feature_contract

MODEL_PATH = Path(__file__).resolve().parents[2] / "models_store" / "expected_delay_xgboost_v1.pkl"


def predict(payload: dict) -> float:
    """payload must contain every field in feature_contract_v2.json's feature_order
    (see ml/service/ml_api.py::DelayPredictionRequest for the field list)."""
    contract = load_feature_contract()
    model = joblib.load(MODEL_PATH)
    features = build_delay_features(pd.DataFrame([payload]), contract)
    return float(model.predict(features)[0])
