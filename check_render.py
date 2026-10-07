# Read-only: checks the cleaned-link column after the migration.
import os

from sqlalchemy import create_engine, inspect, text

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

engine = create_engine(url)
columns = [c["name"] for c in inspect(engine).get_columns("projects")]
col = "normalized_url" if "normalized_url" in columns else "normalized_link"

with engine.connect() as conn:
    total = conn.execute(text("SELECT COUNT(*) FROM projects")).scalar()
    empty = conn.execute(text(f"SELECT COUNT(*) FROM projects WHERE {col} IS NULL OR {col} = ''")).scalar()
    different = conn.execute(text(f"SELECT COUNT(*) FROM projects WHERE {col} <> group_link")).scalar()

print(f"reports: {total}")
print(f"without a cleaned link: {empty}")
print(f"cleaned link differs from the original: {different}")