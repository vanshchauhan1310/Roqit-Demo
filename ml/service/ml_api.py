from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.models import eta_prediction

app = FastAPI(title="Fleet Optimization ML Service")


class EtaPredictionRequest(BaseModel):
    distance_km: float
    num_stops: int
    hour_of_day: int
    day_of_week: int
    avg_historical_speed_kph: float


class EtaPredictionResponse(BaseModel):
    predicted_duration_minutes: float


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/predict/eta", response_model=EtaPredictionResponse)
def predict_eta(request: EtaPredictionRequest):
    try:
        duration = eta_prediction.predict(request.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="ETA model not trained yet. Run src/train.py --model eta first.")
    return EtaPredictionResponse(predicted_duration_minutes=duration)
