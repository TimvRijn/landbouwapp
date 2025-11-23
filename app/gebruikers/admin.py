import os
import uuid
import hashlib
import psycopg2
from dotenv import load_dotenv

# .env inladen (zodat DATABASE_URL beschikbaar is)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is niet gezet in de omgeving / .env")

# Verbind met PostgreSQL
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

password = 'admin123'
password_hash = hashlib.sha256(password.encode()).hexdigest()

# Als je een UNIQUE constraint op username hebt kun je ON CONFLICT gebruiken
sql = """
INSERT INTO users (id, username, password_hash, email, naam, is_admin)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (username) DO NOTHING;
"""

cur.execute(
    sql,
    (
        str(uuid.uuid4()),
        'admin',
        password_hash,
        'admin@demo.nl',
        'Admin',
        1,  # of 1, afhankelijk van je kolomtype (boolean/int)
    ),
)

conn.commit()
cur.close()
conn.close()

print("Admin-user toegevoegd (of bestond al).")
