from app.db.session import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text('UPDATE alembic_version SET version_num = \'b43192b98712\''))
    conn.commit()
    print("Updated alembic_version to b43192b98712")