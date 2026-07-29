from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import trips, routes, vehicles, drivers, realtime, reports
from app.core.config import settings

app = FastAPI(title="Fleet Optimization Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.BACKEND_CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(trips.router, prefix="/api")
app.include_router(routes.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(drivers.router, prefix="/api")
app.include_router(realtime.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
