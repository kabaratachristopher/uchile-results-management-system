from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default='admin')
    full_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    reset_token = db.Column(db.String(100))
    reset_token_expiry = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Class(db.Model):
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    stream = db.Column(db.String(10))
    level = db.Column(db.String(10))
    curriculum = db.Column(db.String(20), default='NEW')  # 'NEW' or 'OLD'
    academic_year = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    cno = db.Column(db.String(20), unique=True, nullable=False)
    admission_number = db.Column(db.String(20))
    prem_number = db.Column(db.String(20))
    first_name = db.Column(db.String(50), nullable=False)
    middle_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50), nullable=False)
    sex = db.Column(db.String(1))
    date_of_birth = db.Column(db.Date)
    passport_photo = db.Column(db.String(200))
    parent_name = db.Column(db.String(100))
    parent_contact = db.Column(db.String(20))
    parent_email = db.Column(db.String(120))
    address = db.Column(db.Text)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))
    combination = db.Column(db.String(10))
    is_active = db.Column(db.Boolean, default=True)
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False)
    short_code = db.Column(db.String(15))
    level = db.Column(db.String(10))
    category = db.Column(db.String(20))
    max_score = db.Column(db.Integer, default=100)
    pass_mark = db.Column(db.Integer, default=30)
    is_active = db.Column(db.Boolean, default=True)

class StudentSubject(db.Model):
    __tablename__ = 'student_subjects'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subject = db.relationship('Subject', backref='student_subjects')

class ExamRecord(db.Model):
    __tablename__ = 'exam_records'
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    exam_type = db.Column(db.String(50), nullable=False)
    month = db.Column(db.String(20), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    exam_class = db.relationship('Class', backref='exam_records')

class Result(db.Model):
    __tablename__ = 'results'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    exam_record_id = db.Column(db.Integer, db.ForeignKey('exam_records.id'), nullable=False)
    raw_score = db.Column(db.Float, nullable=False)
    grade = db.Column(db.String(5))
    points = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subject = db.relationship('Subject', backref='results')

class Behavior(db.Model):
    __tablename__ = 'behaviors'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    exam_record_id = db.Column(db.Integer, db.ForeignKey('exam_records.id'), nullable=False)
    heshima = db.Column(db.String(2), default='B')
    ushirikiano = db.Column(db.String(2), default='B')
    kujituma = db.Column(db.String(2), default='B')
    usafi = db.Column(db.String(2), default='B')
    nidhamu = db.Column(db.String(2), default='B')
    uaminifu = db.Column(db.String(2), default='B')
    class_teacher_comment = db.Column(db.Text)
    academic_master_comment = db.Column(db.Text)
    head_of_school_comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

class PromotionHistory(db.Model):
    __tablename__ = 'promotion_history'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    from_class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    to_class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    exam_record_id = db.Column(db.Integer, db.ForeignKey('exam_records.id'))
    promoted_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    promoted_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_rolled_back = db.Column(db.Boolean, default=False)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)