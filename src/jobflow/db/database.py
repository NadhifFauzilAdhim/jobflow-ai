"""Database connection and session handling."""

import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from jobflow.config import settings
from jobflow.db.models import Base

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Initialize database tables and auto-seed profile if table is empty."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Auto-seed profile from master_profile.json if empty
    try:
        from jobflow.db.profile_repo import get_active_profile
        async with async_session() as session:
            await get_active_profile(session)
    except Exception as e:
        import logging
        logging.getLogger("jobflow.db").warning(f"Could not auto-seed profile during init_db: {e}")


async def get_db():
    """Dependency for API database session."""
    async with async_session() as session:
        yield session
