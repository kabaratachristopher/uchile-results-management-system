from app import app, db
from models import Class

with app.app_context():
    classes = Class.query.filter_by(level='O-LEVEL').order_by(Class.name).all()
    for c in classes:
        print(f'Form {c.name}: {c.curriculum or "NEW"}')