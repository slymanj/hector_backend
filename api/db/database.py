# api/db/database.py

from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from sqlalchemy import create_engine
from api.utils.settings import settings

DB_HOST = settings.DB_HOST
DB_PORT = settings.DB_PORT
DB_USER = settings.DB_USER
DB_PASSWORD = settings.DB_PASSWORD
DB_NAME = settings.DB_NAME
DB_TYPE = settings.DB_TYPE

def get_db_engine(test_mode: bool = False):
    """
    Create and return a SQLAlchemy engine for the database.
    
    Args:
        test_mode: If True, configure for testing (optional, can be removed if not needed).
    
    Returns:
        SQLAlchemy engine instance.
    """
    if test_mode:
        # Optional: Support SQLite for testing if needed
        DATABASE_URL = "sqlite:///test.db"
        return create_engine(
            DATABASE_URL, connect_args={"check_same_thread": False}
        )
    
    if DB_TYPE == "postgresql":
        DATABASE_URL = (
            f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
        return create_engine(DATABASE_URL)
    
    raise ValueError(f"Unsupported DB_TYPE: {DB_TYPE}")

engine = get_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)
Base = declarative_base()

def create_database():
    """
    Create all tables defined in the models.
    """
    return Base.metadata.create_all(bind=engine)

def get_db():
    """
    Dependency to provide a database session.
    """
    db = db_session()
    try:
        yield db
    finally:
        db.close()