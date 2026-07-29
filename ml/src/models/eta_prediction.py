from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error

from src.features.build_features import build_eta_features

MODEL_PATH = Path(__file__).resolve().parents[2] / "models_store" / "eta_prediction.joblib"


def train(df: pd.DataFrame) -> dict:
    X = build_eta_features(df)
    y = df["actual_duration_minutes"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestRegressor(n_estimators=200, max_depth=8, random_state=42)
    model.fit(X_train, y_train)

    mae = mean_absolute_error(y_test, model.predict(X_test))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    return {"model_path": str(MODEL_PATH), "mae_minutes": mae, "n_samples": len(df)}


def predict(payload: dict) -> float:
    model = joblib.load(MODEL_PATH)
    features = pd.DataFrame([payload])
    return float(model.predict(features)[0])
