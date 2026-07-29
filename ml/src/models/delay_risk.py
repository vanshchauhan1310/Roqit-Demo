# Predicts probability that a trip will be delayed (status == "Delayed", i.e.
# delay_minutes > 90) using real business ground truth (see ../../pipeline_documentation_v2.json).
#
# v2 supersedes the original leakage-prone model (see project memory / v1 docs):
# v1's gps_point_density feature was mathematically derived from the same
# route_duration_hours used to build its target, and its group-split AUC (~0.33,
# worse than random) showed the ~0.76 CV number was an artifact. v2 is trained on
# 1298 real trips with a real business target and no dominant/leaked feature,
# reaching a genuine 0.65-0.73 AUC.

from pathlib import Path

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

from src.features.build_features import build_delay_features, load_feature_contract

MODEL_PATH = Path(__file__).resolve().parents[2] / "models_store" / "delay_risk_xgboost_v2.pkl"

HYPERPARAMS = dict(
    n_estimators=33,
    learning_rate=0.05,
    max_depth=4,
    eval_metric="logloss",
    enable_categorical=True,
    random_state=42,
)


def train(df: pd.DataFrame) -> dict:
    contract = load_feature_contract()
    X = build_delay_features(df, contract)
    y = df["is_delayed"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = XGBClassifier(**HYPERPARAMS)
    model.fit(X_train, y_train)

    test_auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    return {"model_path": str(MODEL_PATH), "test_auc": test_auc, "n_samples": len(df)}


def predict(payload: dict) -> dict:
    """payload must contain every field in feature_contract_v2.json's feature_order
    (see ml/service/ml_api.py::DelayPredictionRequest for the field list)."""
    contract = load_feature_contract()
    model = joblib.load(MODEL_PATH)
    features = build_delay_features(pd.DataFrame([payload]), contract)

    delay_probability = float(model.predict_proba(features)[0, 1])
    return {
        "delay_probability": delay_probability,
        "is_delayed_prediction": delay_probability >= 0.5,
    }
