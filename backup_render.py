# Read-only: lists every table in the database in DATABASE_URL and saves a CSV copy of each one.
import csv
import datetime
import os

from sqlalchemy import create_engine, inspect, text

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

engine = create_engine(url)
folder = "render_backup_" + datetime.datetime.now().strftime("%Y%m%d-%H%M")
os.makedirs(folder)

inspector = inspect(engine)
with engine.connect() as conn:
    for table in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns(table)]
        rows = conn.execute(text(f'SELECT * FROM "{table}"')).fetchall()
        with open(f"{folder}/{table}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        print(f"{table}: {len(rows)} rows, columns: {columns}")

print(f"\nBackup saved in the folder: {folder}")