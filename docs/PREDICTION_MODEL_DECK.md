# Prediction Model Deck — Why It Wasn't Predicting (and How We Fixed It)

**Date:** 2026-09-04 · **Stack:** FastAPI (backend) + XGBoost (ml service) + Postgres + Docker Compose

---

## 1. The Prediction Pipeline (How It's Supposed to Work)

```
GPS / realtime_fleet_status ──► POST /api/predictions/delay/latest
POST /api/predictions/delay/trips/{trip_id}
            │
            ▼
┌────────────────────────── backend: delay_prediction_service ──────────────────────────┐
│ 1. Fetch trip (+ vehicle, driver)                                                     │
│ 2. Load feature contract      ml/feature_contract_v2.json  (25 fields, vocabularies)  │
│ 3. Engineer features          planned_duration, avg speed, per-driver/vehicle/route    │
│                               history stats, live weather (OpenWeather → ML vocab)    │
│ 4. Validate                   null checks → category vocabulary → numeric ranges      │
└──────────────────────────────────────┬────────────────────────────────────────────────┘
                                       ▼
                    POST ml:8001/predict/delay  (XGBoost, delay_risk_xgboost_v2)
                                       ▼
                    Store in delay_predictions → return JSON to frontend
```

**Models served by the ML container (port 8001):**

| Model | Endpoint | Output |
|---|---|---|
| `delay_risk_xgboost_v2` | `/predict/delay` | `delay_probability` (0–1) + `is_delayed_prediction` |
| Expected-delay regressor | `/predict/expected-delay` | `predicted_delay_minutes` |
| Fuel consumption | `/predict/fuel-liters` | `predicted_fuel_liters` |
| Trip cost | `/predict/trip-cost` | cost estimate |

**Fallback:** if the ML service is unreachable, the backend substitutes a deterministic
rule-based score (weather/traffic/road risk tables) with `model_version = rule_based_fallback`.

---

## 3. Root Causes (in the order the pipeline hits them)

### RC1 — Feature contract file missing inside the backend container 🔴 *the 500*
`delay_prediction_service.py` resolves the contract at
`Path(__file__).parents[3] / "ml" / "feature_contract_v2.json"` → **`/ml/feature_contract_v2.json`**
in the container. But the backend image only `COPY`s `./backend`, so the file never exists there:

```
FileNotFoundError: [Errno 2] No such file or directory: '/ml/feature_contract_v2.json'
```

Every prediction request died at step 2 of feature engineering. **This was the primary
"model is not predicting" bug.**

**Fix:** read-only bind mount in `docker-compose.yml`:
```yaml
backend:
  volumes:
    - ./ml/feature_contract_v2.json:/ml/feature_contract_v2.json:ro
```

### RC2 — `realtime_fleet_status` empty → the 404
`/latest` picks its trip via the most recently updated `realtime_fleet_status` row.
The table had **0 rows**, so the endpoint correctly reported "no active trip".

**Fix:** seeded one row per assigned vehicle (same logic as `seed_demo_data.py`);
in a live deployment this table is populated by the GPS/simulator feed.

### RC3 — Trips missing required model inputs → the 422s
The contract requires 25 features. Database audit found:

| Field | Populated |
|---|---|
| gps coords, road_type, traffic_density, fuel_price_per_l | 181/181 ✅ |
| **planned_distance_km** | **0/181 ❌** |
| **pickup_time / planned_delivery_time** | **0/181 ❌** |
| **weather_condition** | **0/181 ❌** |
| vehicle `fuel_type` (NULL or `"diesel"` — contract needs `"Diesel"`) | 14 vehicles ❌ |
| driver `base_location` (DRV007–009) | NULL ❌ |
| driver `experience_years` (DRV007–009) | NULL ❌ |

The seeder never wrote these columns, so even with RC1 fixed, feature validation
rejected every trip.

**Fix:** `backend/fix_prediction_data.py` (idempotent):
1. `fuel_type` casing/NULLs → `"Diesel"`
2. `base_location` → `"Hyderabad"`, `experience_years` → `5.0`
3. `planned_distance_km` → real OSRM road-route distance (also `actual_distance_km`)
4. `pickup_time` → now; `planned_delivery_time` → pickup + distance/40 kmph
5. `weather_condition` → `"Clear"` (no `OPENWEATHER_API_KEY` configured, so live lookup can't resolve)



---

## 2. Symptoms

| Symptom | Where seen |
|---|---|
| `POST /api/predictions/delay/latest` → **404** "No vehicles with an active trip found" | Backend API |
| `POST /api/predictions/delay/trips/{trip_id}` → **500** internal error | Backend API |
| `delay_predictions` table: **0 rows** — nothing ever persisted | Postgres |
| Frontend delay widgets empty / errors | UI |

The ML container itself was **healthy** (all healthchecks 200 OK) — the failure was
upstream of it.

---

## 4. Secondary issue found & fixed

The first run of the repair script died with
`OperationalError: server closed the connection unexpectedly` — Postgres' **idle-in-transaction
timeout** killed the session while the script waited on slow per-trip OSRM calls inside one open
transaction. Fixed by committing per-trip instead of one giant transaction.

---

## 5. Verification (after fixes)

| Check | Result |
|---|---|
| Contract visible in backend container | ✅ `exists: True` |
| `POST /api/predictions/delay/trips/TRP-7D59CD96` | ✅ `delay_probability = 0.054`, `is_delayed = false`, **`delay_risk_xgboost_v2`** |
| `POST /api/predictions/expected-delay/trips/TRP-7D59CD96` | ✅ `predicted_delay_minutes = 45.9` |
| `POST /api/predictions/delay/latest` | ✅ picks GPS-latest trip, predicts via XGBoost |
| `delay_predictions` table | ✅ rows persisted, `model_version = delay_risk_xgboost_v2` |
| ML container direct test | ✅ `{"predicted_fuel_liters": 101.86}` |

The `model_version` in the stored rows proves requests reach the **real XGBoost model**
(not the rule-based fallback).

---

## 6. Takeaways / Recommendations

1. **Cross-service file dependencies break silently in Docker.** The contract lives in `ml/`
   but is read by `backend/`. Prefer: baking it into the backend image, fetching it from the ML
   service at startup, or (as done) an explicit compose bind mount.
2. **The feature contract's strict "flag, don't fix" validation is good** — it surfaced the
   data-quality gaps (RC3) as explicit 422s instead of garbage-in/garbage-out predictions.
3. **Seed data must satisfy the model contract.** Add the seeder's missing fields
   (`planned_distance_km`, times, weather, driver attributes) to `seed_fleet.py` /
   `seed_demo_data.py` so fresh environments don't reproduce RC3.
4. **Observability:** surface `model_version` in the frontend so users can see whether a
   displayed prediction came from the ML model or the rule-based fallback.
5. **Long-running scripts + Postgres:** commit incrementally; one open transaction across
   slow external calls will hit `idle_in_transaction_session_timeout`.

---

## 7. Reproduce / Re-run

```bash
# 1. Fix data gaps (idempotent)
docker compose exec backend python fix_prediction_data.py

# 2. Predict for a specific trip
curl -X POST http://localhost:8000/api/predictions/delay/trips/TRP-7D59CD96

# 3. Predict for the GPS-latest trip
curl -X POST http://localhost:8000/api/predictions/delay/latest

# 4. Check persisted predictions
docker compose exec postgres psql -U fleet -d fleet_db \
  -c "SELECT trip_id, delay_probability, is_delayed_prediction, model_version, predicted_at FROM delay_predictions ORDER BY predicted_at DESC LIMIT 5"
```

