import json
from pathlib import Path

import pandas as pd

FEATURE_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "feature_contract_v2.json"


def build_eta_features(df: pd.DataFrame) -> pd.DataFrame:
    """Turns raw trip rows into the numeric feature set the ETA model trains on."""
    features = pd.DataFrame()
    features["distance_km"] = df["distance_km"]
    features["num_stops"] = df["num_stops"]
    features["hour_of_day"] = pd.to_datetime(df["scheduled_start"]).dt.hour
    features["day_of_week"] = pd.to_datetime(df["scheduled_start"]).dt.dayofweek
    features["avg_historical_speed_kph"] = df["avg_historical_speed_kph"]
    return features


def load_feature_contract(path: Path = FEATURE_CONTRACT_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


# fuel_l_xgboost_v1.pkl / trip_cost_xgboost_v1.pkl's real trained schema, read directly
# off the model's own booster.feature_names/feature_types (not guessed) - see
# models_store inspection. Categorical vocab for all 5 'c' columns here happens to be
# a subset of feature_contract_v2.json's, so no separate contract file is needed.
COST_FEATURE_ORDER = [
    "vehicle_type", "road_type", "traffic_density", "weather_condition", "fuel_type",
    "planned_distance_km", "load_weight_kg", "avg_kmpl_rated", "vehicle_age_years", "fuel_price_per_l",
]
COST_CATEGORICAL_FEATURES = {"vehicle_type", "road_type", "traffic_density", "weather_condition", "fuel_type"}
COST_INT_FEATURES = {"load_weight_kg", "vehicle_age_years"}


def build_cost_features(df: pd.DataFrame, contract: dict | None = None) -> pd.DataFrame:
    """Turns raw trip+vehicle rows into the exact 10-column frame fuel_consumption/
    trip_cost's XGBRegressors expect, in the model's own trained column order/dtypes."""
    contract = contract or load_feature_contract()
    categorical_vocabulary = contract["categorical_vocabulary"]

    features = pd.DataFrame(index=df.index)
    for col in COST_FEATURE_ORDER:
        if col not in df.columns:
            raise KeyError(f"Missing required feature column: {col}")

        if col in COST_CATEGORICAL_FEATURES:
            features[col] = pd.Categorical(df[col], categories=categorical_vocabulary[col])
        elif col in COST_INT_FEATURES:
            features[col] = pd.to_numeric(df[col]).astype(int)
        else:
            features[col] = pd.to_numeric(df[col])

    return features[COST_FEATURE_ORDER]


def build_delay_features(df: pd.DataFrame, contract: dict | None = None) -> pd.DataFrame:
    """Turns raw trip rows into the exact 25-column frame delay_risk's XGBClassifier
    expects, in feature_contract_v2.json's order and dtypes (categorical dtype for
    enable_categorical=True columns, everything else numeric)."""
    contract = contract or load_feature_contract()
    feature_order = contract["feature_order"]
    categorical_features = set(contract["categorical_features"])
    boolean_features = set(contract["boolean_features"])
    categorical_vocabulary = contract["categorical_vocabulary"]

    features = pd.DataFrame(index=df.index)
    for col in feature_order:
        if col not in df.columns:
            raise KeyError(f"Missing required feature column: {col}")

        if col in categorical_features:
            categories = categorical_vocabulary[col]
            features[col] = pd.Categorical(df[col], categories=categories)
        elif col in boolean_features:
            features[col] = df[col].astype(bool).astype(int)
        else:
            features[col] = pd.to_numeric(df[col])

    return features[feature_order]
