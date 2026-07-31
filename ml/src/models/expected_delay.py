# Predicts expected delay in minutes for a trip (a continuous regression target,
# distinct from delay_risk's P(delayed) classifier), using the same 25-field
# feature set as delay_risk (see ml/feature_contract_v2.json).
#
# The shipped artifact (models_store/expected_delay_xgboost_v1.pkl) was trained
# externally - this module intentionally only implements predict(), not train(),
# since the exact hyperparameters/target used for that artifact aren't recorded
# in this repo and shouldn't be guessed at and presented as a reproduction.

from pathlib import Path

import joblib
import pandas as pd

from src.features.build_features import build_delay_features, load_feature_contract

MODEL_PATH = Path(__file__).resolve().parents[2] / "models_store" / "expected_delay_xgboost_v1.pkl"


def predict(payload: dict) -> dict:
    """payload must contain every field in feature_contract_v2.json's feature_order
    (see ml/service/ml_api.py::DelayPredictionRequest for the field list)."""
    contract = load_feature_contract()
    model = joblib.load(MODEL_PATH)
    features = build_delay_features(pd.DataFrame([payload]), contract)

    predicted_delay_minutes = float(model.predict(features)[0])
    return {"predicted_delay_minutes": predicted_delay_minutes}
