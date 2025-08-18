import sqlite3
import uuid
import hashlib

conn = sqlite3.connect('database.db')
c = conn.cursor()
password = 'admin123'
password_hash = hashlib.sha256(password.encode()).hexdigest()
c.execute("""
INSERT INTO users (id, username, password_hash, email, naam, is_admin)
VALUES (?, ?, ?, ?, ?, ?)
""", (str(uuid.uuid4()), 'admin', password_hash, 'admin@demo.nl', 'Admin', 1))
conn.commit()
conn.close()
