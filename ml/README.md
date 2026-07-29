# ML Service

Standalone Python service for Fleet Optimization Platform models. Runs independently of the backend — the backend calls it over HTTP via `app/services/ml_client.py`.

## Layout

- `data/raw/` — place source CSVs here (e.g. `trips.csv` for ETA training).
- `data/processed/` — output of feature engineering.
- `src/features/build_features.py` — shared feature engineering pipeline.
- `src/models/` — one module per model (eta_prediction, delay_risk, fuel_efficiency_anomaly, predictive_maintenance, driver_risk_score).
- `src/train.py` — CLI to train a given model.
- `src/predict.py` — CLI/import to run inference against a saved model.
- `models_store/` — trained model artifacts (`.pkl` / `.joblib`).
- `service/ml_api.py` — FastAPI service exposing `/predict/*` endpoints.

## Delay risk model (v2)

`src/models/delay_risk.py` predicts P(trip delayed), where "delayed" is the real
business outcome (`status == "Delayed"`, i.e. `delay_minutes > 90`) — not a
self-constructed proxy. See `pipeline_documentation_v2.json` for full performance
notes (genuine 0.65-0.73 AUC, no leaked/dominant feature) and `feature_contract_v2.json`
for the exact 25-field input schema, categorical vocabularies, and boolean fields
that `/predict/delay` and `delay_risk.predict()` expect.

The shipped artifact (`models_store/delay_risk_xgboost_v2.pkl`) was trained
externally on `data/raw/master_trips_phase5.csv` (1298 trips); `data/processed/train_v2.csv`
/ `test_v2.csv` are the exact split used to report `test_auc`. To retrain from
scratch: `python src/train.py --model delay --input data/raw/master_trips_phase5.csv`.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Train the ETA model (expects ml/data/raw/trips.csv)
python src/train.py --model eta --input data/raw/trips.csv

# Serve predictions
uvicorn service.ml_api:app --reload --port 8001
```

## Adding a new model

1. Add a module in `src/models/` with a `train()` and `predict()` function.
2. Wire it into `src/train.py` (`--model <name>` option).
3. Add a `/predict/<name>` endpoint in `service/ml_api.py` that loads the saved artifact from `models_store/` and reuses the module's `predict()`.
