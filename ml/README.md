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
