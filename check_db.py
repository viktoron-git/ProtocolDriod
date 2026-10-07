from extensions import app, db
from models import Projects

with app.app_context():
    for p in db.session.execute(db.select(Projects)).scalars():
        print(f"{p.group_link} '->' {p.normalized_link}")