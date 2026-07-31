# Predicts fuel consumption in liters for a trip, using the 10-field feature set
# read directly off the trained model's own booster metadata (see
# build_features.COST_FEATURE_ORDER) - not build_delay_features' 25 fields.
#
# The shipped artifact (models_store/fuel_l_xgboost_v1.pkl) was trained externally -
# this module intentionally only implements predict(), not train(), for the same
# reason as expected_delay.py: the real hyperparameters/target aren't recorded here.

from pathlib import Path

import joblib
import pandas as pd

from src.features.build_features import build_cost_features, load_feature_contract

MODEL_PATH = Path(__file__).resolve().parents[2] / "models_store" / "fuel_l_xgboost_v1.pkl"


def predict(payload: dict) -> dict:
    """payload must contain every field in build_features.COST_FEATURE_ORDER."""
    contract = load_feature_contract()
    model = joblib.load(MODEL_PATH)
    features = build_cost_features(pd.DataFrame([payload]), contract)

    predicted_fuel_liters = float(model.predict(features)[0])
    return {"predicted_fuel_liters": predicted_fuel_liters}
