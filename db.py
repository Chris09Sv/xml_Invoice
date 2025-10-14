# db.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pandas as pd
def get_session(db_url: str):
    """Devuelve una sesión de SQLAlchemy para PostgreSQL."""
    engine = create_engine(db_url)  # ej: "postgresql+psycopg://user:pass@host:5432/db"
    return sessionmaker(bind=engine)()

def get_connection(db):
    database = 'postgresql+psycopg2://admin:admin@localhost:5432/examin'

    db =database
    return  create_engine(db)


df = pd.read_sql('select * from Header', get_connection(''))

    

print(df)