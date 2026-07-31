# Predicts total trip cost, using the same 10-field feature set as fuel_consumption
# (see build_features.COST_FEATURE_ORDER), read directly off the trained model's
# own booster metadata.
#
# The shipped artifact (models_store/trip_cost_xgboost_v1.pkl) was trained externally -
# this module intentionally only implements predict(), not train(), same reasoning
# as expected_delay.py/fuel_consumption.py.

from pathlib import Path

import joblib
import pandas as pd

from src.features.build_features import build_cost_features, load_feature_contract

MODEL_PATH = Path(__file__).resolve().parents[2] / "models_store" / "trip_cost_xgboost_v1.pkl"


def predict(payload: dict) -> dict:
    """payload must contain every field in build_features.COST_FEATURE_ORDER."""
    contract = load_feature_contract()
    model = joblib.load(MODEL_PATH)
    features = build_cost_features(pd.DataFrame([payload]), contract)

    predicted_trip_cost = float(model.predict(features)[0])
    return {"predicted_trip_cost": predicted_trip_cost}
