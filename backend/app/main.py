from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import trips, routes, vehicles, drivers, realtime, reports, geocode, roster, predictions
from app.core.config import settings
from app.workers.supervisor import supervisor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background optimization workers (trip assignment + LNS)."""
    supervisor.start()
    try:
        yield
    finally:
        supervisor.stop()


app = FastAPI(title="Fleet Optimization Platform API", lifespan=lifespan)

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
app.include_router(geocode.router, prefix="/api")
app.include_router(roster.router, prefix="/api")
app.include_router(predictions.router, prefix="/api")
app.include_router(predictions.expected_delay_router, prefix="/api")
