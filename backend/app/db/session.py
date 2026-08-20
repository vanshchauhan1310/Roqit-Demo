from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Supabase's session-mode pooler caps this whole app (backend + ml service +
# any local scripts) at 15 concurrent connections TOTAL. The ml service never
# touches the DB directly, so in practice this engine only shares the budget
# with occasional one-off scripts (backfill_*.py, smoke_test_*.py). A single
# trip-detail page load fires ~6-7 concurrent requests, several of which hold
# their connection open across an awaited external HTTP call (ML/weather, up
# to 10s) before releasing it - pool_size=3/overflow=2 (5 total) was too thin
# for that burst and caused QueuePool timeouts. Raised to 12, still well under
# the 15 ceiling so scripts always have headroom.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=8, max_overflow=4)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
