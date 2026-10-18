DATABASE_URL=""


import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

engine = create_engine(DATABASE_URL)

with engine.connect() as connection:
    print(connection.execute(text("SELECT version()")).scalar())