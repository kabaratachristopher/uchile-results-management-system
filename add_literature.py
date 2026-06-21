from app import app, db
from models import Subject

with app.app_context():
    s = Subject.query.filter_by(code='024').first()
    if not s:
        s = Subject(code='024', name='LITERATURE IN ENGLISH', short_code='LIT', 
                   level='O-LEVEL', category='OPTIONAL')
        db.session.add(s)
        db.session.commit()
        print('Literature in English (024) added!')
    else:
        print('Already exists:', s.name)