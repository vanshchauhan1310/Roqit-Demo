# Predicts fuel consumption in liters for a trip, using the 10-field feature set
# read directly off the trained model's own booster metadata (see
# build_features.COST_FEATURE_ORDER) - not build_delay_features' 25 fields.
#
# The shipped artifact (models_store/fuel_l_xgboost_v1.pkl) was trained externally -
# this module intentionally only implements predict(), not train(), for the same
# reason as expected_delay.py: the real hyperparameters/target aren't recorded here.

from pathlib import Path
from typing import List, Dict, Any

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


def predict_sequence(
    base_payload: dict,
    segment_distances_km: List[float],
    segment_loads_kg: List[float] = None
) -> List[Dict[str, Any]]:
    """
    Predict fuel consumption for each segment in a route sequence.
    
    Args:
        base_payload: Base payload with vehicle/road/traffic features (excluding distance and load)
        segment_distances_km: List of distances for each segment (A-B, B-C, C-D, ...)
        segment_loads_kg: Optional list of loads for each segment. If not provided, uses base_payload load_weight_kg.
    
    Returns:
        List of predictions for each segment with segment index, distance, load, and predicted fuel.
    """
    contract = load_feature_contract()
    model = joblib.load(MODEL_PATH)
    
    if segment_loads_kg is None:
        segment_loads_kg = [base_payload.get("load_weight_kg", 0)] * len(segment_distances_km)
    
    results = []
    for i, (distance_km, load_kg) in enumerate(zip(segment_distances_km, segment_loads_kg)):
        payload = base_payload.copy()
        payload["planned_distance_km"] = distance_km
        payload["load_weight_kg"] = load_kg
        
        features = build_cost_features(pd.DataFrame([payload]), contract)
        predicted_fuel_liters = float(model.predict(features)[0])
        
        results.append({
            "segment_index": i,
            "segment_name": f"{i}-{i+1}",
            "distance_km": distance_km,
            "load_weight_kg": load_kg,
            "predicted_fuel_liters": predicted_fuel_liters
        })
    
    return results
