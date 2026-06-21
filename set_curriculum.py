from app import app, db
from models import Class

with app.app_context():
    c3 = Class.query.filter_by(name='3', level='O-LEVEL').first()
    c4 = Class.query.filter_by(name='4', level='O-LEVEL').first()
    
    if c3:
        c3.curriculum = 'OLD'
        print('Form III set to Old Curriculum')
    
    if c4:
        c4.curriculum = 'OLD'
        print('Form IV set to Old Curriculum')
    
    db.session.commit()
    print('Done!')