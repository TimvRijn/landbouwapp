import psycopg2

DATABASE_URL="postgresql://database_6pqj_user:ifnHzaBVncvEhclalRip7HN9z4JwaNhC@dpg-d4f10e24d50c73dsvubg-a.frankfurt-postgres.render.com/database_6pqj"

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
cur.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology;")

conn.commit()
cur.close()
conn.close()

print("PostGIS extensions enabled!")
