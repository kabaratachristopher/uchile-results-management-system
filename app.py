from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_cors import CORS
from functools import wraps
from config import Config
from models import db, User, Student, Class, Subject, StudentSubject, ExamRecord, Result, Behavior, PromotionHistory, AuditLog
from utils.necta_grading import *
from utils.subject_config import *
import pandas as pd
from datetime import datetime, timedelta
import io
import os
import secrets
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from collections import defaultdict
from datetime import datetime, timedelta
import cloudinary
import cloudinary.uploader
import cloudinary.api

cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
    api_key=os.environ.get('CLOUDINARY_API_KEY', ''),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', '')
)

# Track login attempts
login_attempts = defaultdict(list)
MAX_ATTEMPTS = 5
LOCKOUT_TIME = 15  # minutes
app = Flask(__name__)
app.config.from_object(Config)
CORS(app)
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    import os
    upload_folder = app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_folder, filename)
    if os.path.exists(file_path):
        return send_from_directory(upload_folder, filename)
    else:
        return "File not found", 404

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_system_info():
    return dict(system_name='Uchile Results Management System',
                system_version='1.0.0',
                school_name='UCHILE SECONDARY SCHOOL',
                school_address='SUMBAWANGA DC - RUKWA REGION',
                current_year=datetime.now().year,
                now=datetime.now())

# ==================== AUTH ROUTES ====================
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'teacher':
            return redirect(url_for('teacher_students'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        login_role = request.form.get('role', '')
        ip = request.remote_addr
        
        # Check if IP is locked out
        now = datetime.now()
        attempts = login_attempts.get(ip, [])
        attempts = [t for t in attempts if now - t < timedelta(minutes=LOCKOUT_TIME)]
        login_attempts[ip] = attempts
        
        if len(attempts) >= MAX_ATTEMPTS:
            remaining = LOCKOUT_TIME - int((now - attempts[0]).total_seconds() / 60)
            flash(f'Too many attempts. Try again in {remaining} minutes.', 'danger')
            return render_template('login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            # Reset attempts on success
            login_attempts[ip] = []
            
            if login_role == 'admin' and user.role != 'admin':
                flash('Please use the Admin Login panel.', 'warning')
                return render_template('login.html')
            if login_role == 'teacher' and user.role != 'teacher':
                flash('Please use the Class Teacher Login panel.', 'warning')
                return render_template('login.html')
            
            login_user(user, remember=True)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            if user.role == 'teacher':
                return redirect(url_for('teacher_students'))
            flash(f'Welcome {user.full_name}!', 'success')
            return redirect(url_for('dashboard'))
        
        # Record failed attempt
        login_attempts[ip].append(now)
        remaining = MAX_ATTEMPTS - len(login_attempts[ip])
        flash(f'Invalid credentials. {remaining} attempts remaining.', 'danger')
    return render_template('login.html')

@app.route('/api/students/reassign-cno', methods=['POST'])
@login_required
@admin_required
def reassign_cno():
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        start_cno = data.get('start_cno', 'S3560-0001')
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Class ID required'}), 400
        
        cl = db.session.get(Class, class_id)
        if not cl:
            return jsonify({'success': False, 'message': 'Class not found'}), 404
        
        parts = start_cno.split('-')
        if len(parts) != 2:
            return jsonify({'success': False, 'message': 'Invalid CNO format. Use S3560-XXXX'}), 400
        
        prefix = parts[0]
        start_num = int(parts[1])
        
        # Define combination order
        combo_order = {'HGK': 1, 'HKL': 2, 'CBG': 3, 'PCB': 4, 'PCM': 5}
        
        # Get active students in this class
        students = Student.query.filter_by(
            class_id=class_id, 
            is_deleted=False
        ).all()
        
        if not students:
            return jsonify({'success': False, 'message': 'No active students found'}), 400
        
        # Sort: by combination order, then alphabetically by first name, then last name
        if cl.level == 'A-LEVEL':
            students.sort(key=lambda s: (
    combo_order.get(s.combination, 99) if s.combination else 99,
    s.first_name.lower(),
    (s.middle_name or '').lower(),
    s.last_name.lower()
))
        else:
               # O-Level: Females first (F=0), then Males (M=1), alphabetical within each
            students.sort(key=lambda s: (
    0 if s.sex == 'F' else 1,
    s.first_name.lower(),
    (s.middle_name or '').lower(),
    s.last_name.lower()
))
        
        # Clear old CNOs
        for s in students:
            s.cno = f"TEMP_REASSIGN_{s.id}"
        db.session.flush()
        
        # Assign new sequential CNOs
        reassigned = 0
        for i, s in enumerate(students):
            new_cno = f"{prefix}-{start_num + i:04d}"
            conflict = Student.query.filter_by(cno=new_cno).first()
            if conflict and conflict.id != s.id:
                continue
            s.cno = new_cno
            reassigned += 1
        
        db.session.commit()
        
        # Build summary message
        msg = f'{reassigned} students reassigned!\n'
        if cl.level == 'A-LEVEL':
            combos = {}
            for s in students:
                comb = s.combination or 'NONE'
                if comb not in combos:
                    combos[comb] = []
                combos[comb].append(s.cno)
            for comb, studs in combos.items():
                if studs:
                    msg += f'{comb}: {studs[0]} to {studs[-1]} ({len(studs)} students)\n'
        
        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==================== DASHBOARD ====================
@app.route('/dashboard')
@login_required
@admin_required
def dashboard():
    ts = Student.query.filter_by(is_deleted=False).count()
    ol = Student.query.join(Class).filter(Class.level == 'O-LEVEL', Student.is_deleted == False).count()
    al = Student.query.join(Class).filter(Class.level == 'A-LEVEL', Student.is_deleted == False).count()
    te = ExamRecord.query.count()
    tsj = Subject.query.count()
    m = Student.query.filter_by(sex='M', is_deleted=False).count()
    f = Student.query.filter_by(sex='F', is_deleted=False).count()
    re = ExamRecord.query.order_by(ExamRecord.created_at.desc()).limit(5).all()
    cs = {}
    for c in Class.query.order_by(Class.name).all():
        cs[f'Form {c.name}'] = Student.query.filter_by(class_id=c.id, is_deleted=False).count()
    return render_template('dashboard.html', total_students=ts, o_level=ol, a_level=al,
                           total_exams=te, total_subjects=tsj, male=m, female=f,
                           recent_exams=re, class_stats=cs)

# ==================== STUDENT MANAGEMENT ====================
@app.route('/students')
@login_required
@admin_required
def students_page():
    s = Student.query.filter_by(is_deleted=False).order_by(Student.admission_number).all()
    ds = Student.query.filter_by(is_deleted=True).order_by(Student.deleted_at.desc()).all()
    c = Class.query.order_by(Class.name).all()
    return render_template('students.html', students=s, deleted_students=ds, classes=c)

@app.route('/api/students/add', methods=['POST'])
@login_required
@admin_required
def add_student():
    try:
        d = request.get_json()
        existing = Student.query.filter_by(cno=d['cno']).first()
        if existing:
            if existing.is_deleted:
                existing.is_deleted = False
                existing.is_active = True
                existing.deleted_at = None
                existing.first_name = d['first_name']
                existing.last_name = d['last_name']
                existing.sex = d.get('sex', 'M')
                existing.class_id = d['class_id']
                existing.combination = d.get('combination', '')
                existing.admission_number = d.get('admission_number', '')
                existing.prem_number = d.get('prem_number', '')
                db.session.commit()
                return jsonify({'success': True, 'message': 'Readmitted'})
            return jsonify({'success': False, 'message': 'CNO already exists'}), 400
        
        dob = None
        if d.get('date_of_birth'):
            dob = datetime.strptime(d['date_of_birth'], '%Y-%m-%d')
        
        st = Student(
            cno=d['cno'],
            admission_number=d.get('admission_number', ''),
            prem_number=d.get('prem_number', ''),
            first_name=d['first_name'],
            middle_name=d.get('middle_name', ''),
            last_name=d['last_name'],
            sex=d.get('sex', 'M'),
            date_of_birth=dob,
            parent_name=d.get('parent_name', ''),
            parent_contact=d.get('parent_contact', ''),
            parent_email=d.get('parent_email', ''),
            address=d.get('address', ''),
            class_id=d['class_id'],
            combination=d.get('combination', '')
        )
        db.session.add(st)
        db.session.flush()
        
        cl = Class.query.get(d['class_id'])
        if cl.level == 'O-LEVEL':
            assign_o_level_subjects(st, d.get('optional_group', ''))
        else:
            assign_a_level_subjects(st, d.get('combination', ''))
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Registered'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


def assign_o_level_subjects(student, group):
    cl = db.session.get(Class, student.class_id)
    
    if cl and cl.curriculum == 'OLD':
        old_compulsory = ['201', '021', '041', '013', '022', '012', '033']
        for code in old_compulsory:
            subj = Subject.query.filter_by(code=code).first()
            if subj:
                existing = StudentSubject.query.filter_by(student_id=student.id, subject_id=subj.id).first()
                if not existing:
                    db.session.add(StudentSubject(student_id=student.id, subject_id=subj.id))
        if group:
            for code in group.split(','):
                code = code.strip()
                if code in OLD_CURRICULUM_CONFIG['optional']:
                    subj = Subject.query.filter_by(code=code).first()
                    if subj:
                        existing = StudentSubject.query.filter_by(student_id=student.id, subject_id=subj.id).first()
                        if not existing:
                            db.session.add(StudentSubject(student_id=student.id, subject_id=subj.id))
    else:
        for code in O_LEVEL_COMPULSORY:
            subj = Subject.query.filter_by(code=code).first()
            if subj:
                existing = StudentSubject.query.filter_by(student_id=student.id, subject_id=subj.id).first()
                if not existing:
                    db.session.add(StudentSubject(student_id=student.id, subject_id=subj.id))
        if group in O_LEVEL_OPTIONAL_GROUPS:
            for code in O_LEVEL_OPTIONAL_GROUPS[group]:
                subj = Subject.query.filter_by(code=code).first()
                if subj:
                    existing = StudentSubject.query.filter_by(student_id=student.id, subject_id=subj.id).first()
                    if not existing:
                        db.session.add(StudentSubject(student_id=student.id, subject_id=subj.id))


def assign_a_level_subjects(student, comb):
    if comb not in A_LEVEL_COMBINATIONS:
        return
    c = A_LEVEL_COMBINATIONS[comb]
    for code in c['core']:
        subj = Subject.query.filter_by(code=code).first()
        if subj:
            existing = StudentSubject.query.filter_by(student_id=student.id, subject_id=subj.id).first()
            if not existing:
                db.session.add(StudentSubject(student_id=student.id, subject_id=subj.id))
    for code in c['subsidiary']:
        subj = Subject.query.filter_by(code=code).first()
        if subj:
            existing = StudentSubject.query.filter_by(student_id=student.id, subject_id=subj.id).first()
            if not existing:
                db.session.add(StudentSubject(student_id=student.id, subject_id=subj.id))

@app.route('/api/students/<int:id>', methods=['GET'])
@login_required
@admin_required
def get_student(id):
    student = Student.query.get_or_404(id)
    student_subjects = StudentSubject.query.filter_by(student_id=id).all()
    return jsonify({
        'id': student.id,
        'cno': student.cno,
        'admission_number': student.admission_number or '',
        'prem_number': student.prem_number or '',
        'passport_photo': student.passport_photo or '',
        'first_name': student.first_name,
        'middle_name': student.middle_name or '',
        'last_name': student.last_name,
        'sex': student.sex,
        'date_of_birth': str(student.date_of_birth) if student.date_of_birth else '',
        'parent_name': student.parent_name or '',
        'parent_contact': student.parent_contact or '',
        'parent_email': student.parent_email or '',
        'address': student.address or '',
        'class_id': student.class_id,
        'combination': student.combination or '',
        'is_active': student.is_active,
        'subjects': [{'code': ss.subject.code, 'short_code': ss.subject.short_code,
                      'name': ss.subject.name} for ss in student_subjects]
    })

@app.route('/api/students/<int:id>', methods=['DELETE'])
@login_required
@admin_required
def delete_student(id):
    st = Student.query.get_or_404(id)
    st.is_deleted = True
    st.is_active = False
    st.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'message': 'Student deleted'})

@app.route('/api/students/<int:id>/readmit', methods=['POST'])
@login_required
@admin_required
def readmit_student(id):
    st = Student.query.get_or_404(id)
    st.is_deleted = False
    st.is_active = True
    st.deleted_at = None
    db.session.commit()
    return jsonify({'success': True, 'message': 'Student readmitted'})

@app.route('/api/students/<int:id>/permanent', methods=['DELETE'])
@login_required
@admin_required
def permanent_delete_student(id):
    st = Student.query.get_or_404(id)
    StudentSubject.query.filter_by(student_id=id).delete()
    Result.query.filter_by(student_id=id).delete()
    Behavior.query.filter_by(student_id=id).delete()
    db.session.delete(st)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Permanently deleted'})

@app.route('/api/students/<int:id>', methods=['PUT'])
@login_required
@admin_required
def update_student(id):
    try:
        student = Student.query.get_or_404(id)
        
        # Handle passport photo upload
        if 'passport' in request.files:
            file = request.files['passport']
            if file and file.filename and file.filename != '':
                ext = file.filename.lower().rsplit('.', 1)[-1] if '.' in file.filename else 'jpg'
            if ext in ['jpg', 'jpeg', 'png']:
                file.seek(0, os.SEEK_END)
                size = file.tell()
                file.seek(0)
                if size <= 204800:
                    try:
                    # Upload to Cloudinary
                        result = cloudinary.uploader.upload(file, folder="uchile_passports")
                        student.passport_photo = result['secure_url']
                    except:
                    # Fallback to local storage
                        filename = f"passport_{id}.{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    student.passport_photo = f"/uploads/{filename}"
        
        # Update text fields
        student.first_name = request.form.get('first_name', student.first_name)
        student.middle_name = request.form.get('middle_name', student.middle_name)
        student.last_name = request.form.get('last_name', student.last_name)
        student.sex = request.form.get('sex', student.sex)
        student.admission_number = request.form.get('admission_number', student.admission_number)
        student.prem_number = request.form.get('prem_number', student.prem_number)
        if request.form.get('date_of_birth'):
            student.date_of_birth = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d')
        if request.form.get('class_id'):
            student.class_id = request.form.get('class_id')
        
                # Handle O-Level optional group changes
        optional_group = request.form.get('optional_group', '')
        if optional_group:
            cl = db.session.get(Class, student.class_id)
            if cl and cl.level == 'O-LEVEL':
                if cl.curriculum == 'OLD':
                    # Remove old optional subjects
                    for code in OLD_CURRICULUM_CONFIG['optional']:
                        subj = Subject.query.filter_by(code=code).first()
                        if subj:
                            StudentSubject.query.filter_by(student_id=id, subject_id=subj.id).delete()
                    db.session.flush()
                    # Add new optional subjects
                    for code in optional_group.split(','):
                        code = code.strip()
                        if code in OLD_CURRICULUM_CONFIG['optional']:
                            subj = Subject.query.filter_by(code=code).first()
                            if subj:
                                db.session.add(StudentSubject(student_id=id, subject_id=subj.id))
                else:
                    # New Curriculum
                    all_optional_codes = []
                    for codes in O_LEVEL_OPTIONAL_GROUPS.values():
                        all_optional_codes.extend(codes)
                    for code in all_optional_codes:
                        subj = Subject.query.filter_by(code=code).first()
                        if subj:
                            StudentSubject.query.filter_by(student_id=id, subject_id=subj.id).delete()
                    db.session.flush()
                    if optional_group in O_LEVEL_OPTIONAL_GROUPS:
                        for code in O_LEVEL_OPTIONAL_GROUPS[optional_group]:
                            subj = Subject.query.filter_by(code=code).first()
                            if subj:
                                db.session.add(StudentSubject(student_id=id, subject_id=subj.id))
        
        # Handle A-Level combination changes
        combination = request.form.get('combination', '')
        if combination:
            cl = db.session.get(Class, student.class_id)
            if cl and cl.level == 'A-LEVEL':
                StudentSubject.query.filter_by(student_id=id).delete()
                db.session.flush()
                student.combination = combination
                assign_a_level_subjects(student, combination)
        
        student.parent_name = request.form.get('parent_name', student.parent_name)
        student.parent_contact = request.form.get('parent_contact', student.parent_contact)
        student.parent_email = request.form.get('parent_email', student.parent_email)
        student.address = request.form.get('address', student.address)
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Student updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/students/bulk-upload', methods=['POST'])
@login_required
@admin_required
def bulk_upload_students():
    try:
        file = request.files['file']
        class_id = request.form.get('class_id')
        og = request.form.get('optional_group', '')
        comb = request.form.get('combination', '')
        cl = Class.query.get(class_id)
        df = pd.read_excel(file)
        print("=" * 50)
        print("Excel columns found:", list(df.columns))
        print("Number of rows:", len(df))
        if len(df) > 0:
            print("First row data:", df.iloc[0].to_dict())
        print("=" * 50)
        added = 0
        errors = []
        
        for i, row in df.iterrows():
            try:
                # Accept both 'cno' and 'admission_number' column names
                if 'cno' in row:
                    cno = str(row['cno'])
                elif 'admission_number' in row:
                    cno = str(row['admission_number'])
                else:
                    errors.append(f"Row {i+2}: No CNO column found")
                    continue
                
                if not cno or cno == 'nan':
                    errors.append(f"Row {i+2}: Empty CNO")
                    continue
                
                existing = Student.query.filter_by(cno=cno).first()
                if existing and not existing.is_deleted:
                    errors.append(f"Row {i+2}: CNO {cno} already exists")
                    continue
                
                if existing and existing.is_deleted:
                    existing.is_deleted = False
                    existing.is_active = True
                    existing.first_name = str(row.get('first_name', existing.first_name))
                    existing.last_name = str(row.get('last_name', existing.last_name))
                    existing.admission_number = str(row.get('admission_number', ''))
                    existing.prem_number = str(row.get('prem_number', ''))
                    db.session.commit()
                    st = existing
                else:
                    first_name = str(row.get('first_name', ''))
                    last_name = str(row.get('last_name', ''))
                    if not first_name or first_name == 'nan':
                        errors.append(f"Row {i+2}: Missing first name")
                        continue
                    
                    st = Student(
                        cno=cno,
                        admission_number=str(row.get('admission_number', '')),
                        prem_number=str(row.get('prem_number', '')),
                        first_name=first_name,
                        middle_name=str(row.get('middle_name', '')),
                        last_name=last_name,
                        sex=str(row.get('sex', 'M')),
                        class_id=class_id,
                        combination=comb if cl.level == 'A-LEVEL' else ''
                    )
                    db.session.add(st)
                    db.session.flush()
                
                if cl.level == 'O-LEVEL':
                    assign_o_level_subjects(st, og)
                else:
                    assign_a_level_subjects(st, comb)
                added += 1
                
            except Exception as e:
                errors.append(f"Row {i+2}: {str(e)}")
                print(f"ERROR Row {i+2}: {str(e)}")
        
        db.session.commit()
        msg = f'{added} students uploaded successfully'
        if errors:
            msg += f'. {len(errors)} errors occurred'
        return jsonify({'success': True, 'message': msg, 'errors': errors[:10]})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

# ==================== SUBJECT MANAGEMENT ====================
@app.route('/subjects')
@login_required
@admin_required
def subjects_page():
    subjects = Subject.query.order_by(Subject.code).all()
    return render_template('subjects.html', subjects=subjects)

@app.route('/api/subjects/initialize', methods=['POST'])
@login_required
@admin_required
def initialize_subjects():
    try:
        added = 0
        for code, info in O_LEVEL_SUBJECTS.items():
            if not Subject.query.filter_by(code=code).first():
                db.session.add(Subject(name=info['name'], code=code, short_code=info['short'],
                                       level='O-LEVEL', category=info['category']))
                added += 1
        for code, info in A_LEVEL_SUBJECTS.items():
            if not Subject.query.filter_by(code=code).first():
                db.session.add(Subject(name=info['name'], code=code, short_code=info['short'],
                                       level='A-LEVEL', category=info['category']))
                added += 1
        db.session.commit()
        return jsonify({'success': True, 'message': f'{added} subjects'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

# ==================== RESULTS MANAGEMENT ====================
@app.route('/results')
@login_required
@admin_required
def results_page():
    classes = Class.query.all()
    exam_records = ExamRecord.query.order_by(ExamRecord.created_at.desc()).all()
    return render_template('results.html', classes=classes, exam_records=exam_records)

@app.route('/api/exam-records', methods=['POST'])
@login_required
@admin_required
def create_exam_record():
    d = request.get_json()
    ex = ExamRecord(class_id=d['class_id'], exam_type=d['exam_type'],
                    month=d['month'], year=d['year'], created_by=current_user.id)
    db.session.add(ex)
    db.session.commit()
    return jsonify({'success': True, 'exam_record_id': ex.id, 'message': 'Exam record created'})

@app.route('/api/exam-records/<int:eid>', methods=['GET'])
@login_required
@admin_required
def get_exam_record(eid):
    er = db.session.get(ExamRecord, eid)
    if er:
        return jsonify({'class_id': er.class_id, 'exam_type': er.exam_type, 'month': er.month, 'year': er.year})
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/exam-records/<int:eid>', methods=['DELETE'])
@login_required
@admin_required
def delete_exam_record(eid):
    er = db.session.get(ExamRecord, eid)
    if not er:
        return jsonify({'error': 'Not found'}), 404
    Result.query.filter_by(exam_record_id=eid).delete()
    db.session.delete(er)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Exam record and all results deleted'})

@app.route('/api/results/upload-scores', methods=['POST'])
@login_required
@admin_required
def upload_scores():
    try:
        er = ExamRecord.query.get(int(request.form.get('exam_record_id')))
        cl = Class.query.get(er.class_id)
        level = cl.level
        df = pd.read_excel(request.files['file'])
        added = 0
        errors = []
        subjects = Subject.query.filter_by(level=level).order_by(Subject.code).all()
        subject_columns = {}
        for subject in subjects:
            for col in df.columns:
                if str(subject.code) in str(col):
                    subject_columns[subject.code] = col
                    break
        for _, row in df.iterrows():
            admission_number = str(row['admission_number'])
            student = Student.query.filter_by(admission_number=admission_number).first()
            if not student:
                errors.append(f"Student {admission_number} not found")
                continue
            for subject_code, col_name in subject_columns.items():
                score_value = row[col_name]
                if pd.notna(score_value) and str(score_value).strip() != '':
                    try:
                        raw_score = float(score_value)
                        subject = Subject.query.filter_by(code=subject_code).first()
                        if subject:
                            if level == 'A-LEVEL':
                                grade = calculate_a_level_grade(raw_score)
                                points = calculate_a_level_points(grade)
                            else:
                                grade = calculate_o_level_grade(raw_score)
                                points = calculate_o_level_points(grade)
                            existing = Result.query.filter_by(
                                student_id=student.id, subject_id=subject.id, exam_record_id=er.id).first()
                            if existing:
                                existing.raw_score = raw_score
                                existing.grade = grade
                                existing.points = points
                            else:
                                db.session.add(Result(student_id=student.id, subject_id=subject.id,
                                                     exam_record_id=er.id, raw_score=raw_score,
                                                     grade=grade, points=points))
                            added += 1
                    except ValueError:
                        errors.append(f"Invalid score for {admission_number} - {subject_code}")
        db.session.commit()
        msg = f'{added} scores processed'
        if errors:
            msg += f'. {len(errors)} errors'
        return jsonify({'success': True, 'message': msg, 'errors': errors[:10]})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/results/view/<int:exam_record_id>')
def view_results(exam_record_id):
    er = ExamRecord.query.get_or_404(exam_record_id)
    cl = Class.query.get(er.class_id)
    level = cl.level
    
    # Get students who have results for this exam (even if promoted)
    results_student_ids = [r.student_id for r in Result.query.filter_by(exam_record_id=exam_record_id).all()]
    students = Student.query.filter(
        (Student.class_id == cl.id) | (Student.id.in_(results_student_ids)),
        Student.is_deleted == False
    ).order_by(Student.admission_number).all()
    
    subjects = Subject.query.filter_by(level=level).order_by(Subject.code).all()
    all_results = []
    
    for st in students:
        sd = {'cno': st.admission_number, 'student_name': f"{st.first_name} {st.last_name}", 
              'sex': st.sex, 'subjects': {}, 'best_seven_points': 0, 'core_points': 0, 
              'division': '', 'num_subjects': 0, 'core_grades': [], 'gpa': 0.0, 'is_absent': True}
        for sj in subjects:
            r = Result.query.filter_by(student_id=st.id, subject_id=sj.id, exam_record_id=er.id).first()
            if r:
                sd['subjects'][sj.code] = {'short_code': sj.short_code, 'grade': r.grade, 'points': r.points}
                sd['num_subjects'] += 1
                sd['is_absent'] = False
                if level == 'A-LEVEL' and sj.category == 'CORE':
                    sd['core_grades'].append(r.grade)
        if sd['is_absent']:
            sd['division'] = 'ABS'
            sd['gpa'] = 0.0
        else:
            if level == 'A-LEVEL':
                all_grades = [s['grade'] for s in sd['subjects'].values()]
                sd['gpa'] = calculate_gpa(all_grades, 'A-LEVEL')
                if len(sd['core_grades']) >= 3:
                    sd['core_points'] = sum(calculate_a_level_points(g) for g in sd['core_grades'][:3])
                    sd['division'] = determine_a_level_division(sd['core_grades'][:3])
            else:
                all_grades = [s['grade'] for s in sd['subjects'].values()]
                sd['gpa'] = calculate_gpa(all_grades, 'O-LEVEL')
                if sd['num_subjects'] >= 7:
                    all_points = [(subj['points'], code) for code, subj in sd['subjects'].items()]
                    all_points.sort()
                    sd['best_seven_points'] = sum(p[0] for p in all_points[:7])
                    sd['division'] = determine_o_level_division(sd['best_seven_points'], 7)
        all_results.append(sd)
    
    ds = {'F': {'REGIST': 0, 'ABSENT': 0, 'SAT': 0, 'I': 0, 'II': 0, 'III': 0, 'IV': 0, '0': 0, 'PASSED': 0},
          'M': {'REGIST': 0, 'ABSENT': 0, 'SAT': 0, 'I': 0, 'II': 0, 'III': 0, 'IV': 0, '0': 0, 'PASSED': 0},
          'T': {'REGIST': 0, 'ABSENT': 0, 'SAT': 0, 'I': 0, 'II': 0, 'III': 0, 'IV': 0, '0': 0, 'PASSED': 0}}
    
    for r in all_results:
        sx = r['sex'].upper() if r['sex'] in ['F', 'M'] else 'M'
        ds[sx]['REGIST'] += 1
        ds['T']['REGIST'] += 1
        if r['is_absent']:
            ds[sx]['ABSENT'] += 1
            ds['T']['ABSENT'] += 1
        else:
            ds[sx]['SAT'] += 1
            ds['T']['SAT'] += 1
            dv = r['division']
            if dv in ['I', 'II', 'III', 'IV', '0']:
                ds[sx][dv] += 1
                ds['T'][dv] += 1
                if dv != '0':
                    ds[sx]['PASSED'] += 1
                    ds['T']['PASSED'] += 1
    
    sp = {}
    for sj in subjects:
        spd = {'code': sj.code, 'short_code': sj.short_code, 'name': sj.name,
               'REG': 0, 'SAT': 0, 'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0, 'S': 0, 'F': 0,
               'PASSED': 0, 'GPA': 0.0, 'COMPETENCE': '-', 'COMPETENCE_COLOR': ''}
        registered_count = StudentSubject.query.filter_by(subject_id=sj.id).join(Student).filter(
            Student.class_id == cl.id, Student.is_deleted == False).count()
        spd['REG'] = registered_count
        gl = []
        for st in students:
            r = Result.query.filter_by(student_id=st.id, subject_id=sj.id, exam_record_id=er.id).first()
            if r:
                spd['SAT'] += 1
                g = r.grade
                if g in spd:
                    spd[g] += 1
                if level == 'A-LEVEL':
                    if g in ['A', 'B', 'C', 'D', 'E', 'S']:
                        spd['PASSED'] += 1
                else:
                    if g in ['A', 'B', 'C', 'D']:
                        spd['PASSED'] += 1
                gl.append(g)
        if gl:
            spd['GPA'] = calculate_gpa(gl, level)
            comp, cc = get_competence_status(spd['GPA'], level)
            spd['COMPETENCE'] = comp
            spd['COMPETENCE_COLOR'] = cc
        sp[sj.code] = spd
    
    bs = sorted(sp.items(), key=lambda x: x[1]['GPA'] if x[1]['GPA'] > 0 else float('inf'))
    rk = sorted([r for r in all_results if not r['is_absent'] and r['num_subjects'] >= (3 if level == 'A-LEVEL' else 7)],
                key=lambda x: (x['core_points'] if level == 'A-LEVEL' else x['best_seven_points']))
    tp = rk[:10]
    bt = rk[-10:][::-1] if len(rk) >= 10 else []
    tps = ds['T']['PASSED']
    all_gpas = [spd['GPA'] for spd in sp.values() if spd['GPA'] > 0]
    cg = round(sum(all_gpas) / len(all_gpas), 2) if all_gpas else 0.0
    
    return render_template('view_results.html', exam_record=er, class_=cl, level=level,
                           subjects=subjects, all_results=all_results, div_summary=ds,
                           subj_perf=sp, best_subjects=bs, top_ten=tp, bottom_ten=bt,
                           centre_gpa=cg, total_passed=tps)

# ==================== REPORT CARD ====================
@app.route('/api/reports/report-card/<int:sid>/<int:eid>')
@login_required
@admin_required
def report_card(sid, eid):
    st = Student.query.get_or_404(sid)
    er = ExamRecord.query.get_or_404(eid)
    cl = Class.query.get(er.class_id)
    level = cl.level
    ss = StudentSubject.query.filter_by(student_id=sid).all()
    results = Result.query.filter_by(student_id=sid, exam_record_id=eid).all()
    behavior = Behavior.query.filter_by(student_id=sid, exam_record_id=eid).first()
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=0.4*inch, rightMargin=0.4*inch,
                           topMargin=0.3*inch, bottomMargin=0.3*inch)
    el = []
    sts = getSampleStyleSheet()
    
    DARK_BLUE = colors.HexColor('#003366')
    CREAM = colors.HexColor('#FFF8F0')
    WHITE = colors.white
    
    title_style = ParagraphStyle('T', parent=sts['Title'], alignment=TA_CENTER, fontSize=16, textColor=WHITE, leading=18)
    subtitle_style = ParagraphStyle('S', parent=sts['Normal'], alignment=TA_CENTER, fontSize=12, textColor=WHITE, leading=14)
    normal_style = ParagraphStyle('N', parent=sts['Normal'], fontSize=12, leading=14)
    small_style = ParagraphStyle('SM', parent=sts['Normal'], fontSize=10, leading=12)
    
    # Header
    hd = [[Paragraph("UCHILE SECONDARY SCHOOL", title_style)],
          [Paragraph("SUMBAWANGA DC - RUKWA REGION", subtitle_style)],
          [Paragraph(f"FORM {cl.name} - {er.exam_type.upper()} - {er.month} {er.year}", title_style)],
          [Paragraph("STUDENT PROGRESS REPORT", subtitle_style)]]
    ht = Table(hd, colWidths=[A4[0] - 0.8*inch])
    ht.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), DARK_BLUE),
                           ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                           ('TOPPADDING', (0, 0), (-1, -1), 6),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    el.append(ht)
    el.append(Spacer(1, 8))
    
    # Header
    el.append(Spacer(1, 8))
    
    # Student Info (left) + Passport (right)
    info_text = f"<b>Name:</b> {st.first_name} {st.middle_name or ''} {st.last_name}<br/>"
    info_text += f"<b>CNO:</b> {st.cno}<br/>"
    info_text += f"<b>Admission:</b> {st.admission_number or 'N/A'}<br/>"
    info_text += f"<b>PREM:</b> {st.prem_number or 'N/A'}<br/>"
    info_text += f"<b>Sex:</b> {st.sex}<br/>"
    info_text += f"<b>Class:</b> Form {cl.name}<br/>"
    info_text += f"<b>Combination:</b> {st.combination or 'N/A'}"
    
    info_para = Paragraph(info_text, normal_style)
    
    # Passport
    if st.passport_photo:
        photo_path = st.passport_photo.replace('/uploads/', '')
        full_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_path)
        if os.path.exists(full_path):
            passport_img = Image(full_path, width=100, height=130)
            info_data = [[info_para, passport_img]]
            info_table = Table(info_data, colWidths=[5.5*inch, 1.5*inch])
            info_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('LEFTPADDING', (1, 0), (1, 0), 10),
            ]))
            el.append(info_table)
        else:
            info_data = [[info_para, Paragraph('<b>[PASSPORT<br/>PHOTO]</b>', small_style)]]
            info_table = Table(info_data, colWidths=[5.5*inch, 1.5*inch])
            info_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'CENTER')]))
            el.append(info_table)
    else:
        info_data = [[info_para, Paragraph('<b>[PASSPORT<br/>PHOTO]</b>', small_style)]]
        info_table = Table(info_data, colWidths=[5.5*inch, 1.5*inch])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('BOX', (1, 0), (1, 0), 1, colors.black),
        ]))
        el.append(info_table)
    
    el.append(Spacer(1, 8))
    
    # Results Table
    td = [['CODE', 'SUBJECT', 'SCORE', 'GRADE', 'REMARKS']]
    total_points = 0
    num_subjects = 0
    cg = []
    for s in ss:
        r = next((x for x in results if x.subject_id == s.subject_id), None)
        if r:
            td.append([s.subject.code, s.subject.name, str(r.raw_score), r.grade, 'Pass' if r.grade != 'F' else 'Fail'])
            total_points += r.points
            num_subjects += 1
            if level == 'A-LEVEL' and s.subject.category == 'CORE':
                cg.append(r.grade)
        else:
            td.append([s.subject.code, s.subject.name, '-', '-', 'Absent'])
    
    cw = [0.6*inch, 3.0*inch, 0.8*inch, 0.7*inch, 1.5*inch]
    t = Table(td, colWidths=cw)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), DARK_BLUE),
                          ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
                          ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                          ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                          ('FONTSIZE', (0, 0), (-1, 0), 10),
                          ('FONTSIZE', (0, 1), (-1, -1), 10),
                          ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
                          ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                          ('ROWBACKGROUNDS', (0, 1), (-1, -1), [CREAM, WHITE]),
                          ('ALIGN', (1, 0), (1, -1), 'LEFT')]))
    el.append(t)
    el.append(Spacer(1, 6))
    
    # Division & GPA
    div = ''
    if level == 'A-LEVEL' and len(cg) >= 3:
        div = determine_a_level_division(cg[:3])
        pts = sum(calculate_a_level_points(g) for g in cg[:3])
        el.append(Paragraph(f"<b>Division: {div} (Core: {pts})</b>", normal_style))
    elif level == 'O-LEVEL' and num_subjects >= 7:
        div = determine_o_level_division(total_points, num_subjects)
        el.append(Paragraph(f"<b>Division: {div} (Total: {total_points})</b>", normal_style))
    if results:
        gpa = calculate_gpa([r.grade for r in results], level)
        el.append(Paragraph(f"<b>GPA: {gpa}</b>", normal_style))
    el.append(Paragraph("A=75-100 B=65-74 C=45-64 D=30-44 F=0-29 | A-Level: A=80-100 B=70-79 C=60-69 D=50-59 E=40-49 S=35-39 F=0-34", small_style))
    el.append(Spacer(1, 6))
    
    # Behavior Section
    el.append(Paragraph("<b>BEHAVIOR & CONDUCT (A=Bora, B=Vizuri, C=Wastani, D=Dhaifu)</b>", normal_style))
    el.append(Spacer(1, 2))
    bh_fields = ['heshima', 'ushirikiano', 'kujituma', 'usafi', 'nidhamu', 'uaminifu']
    bh_labels = ['Heshima', 'Ushirikiano', 'Kujituma', 'Usafi', 'Nidhamu', 'Uaminifu']
    bh_data = [['Behavior', 'Grade', 'Behavior', 'Grade']]
    for i in range(0, 6, 2):
        g1 = getattr(behavior, bh_fields[i], '-') if behavior else '-'
        g2 = getattr(behavior, bh_fields[i+1], '-') if behavior and i+1 < 6 else '-'
        bh_data.append([bh_labels[i], g1, bh_labels[i+1], g2])
    bh_table = Table(bh_data, colWidths=[1.8*inch, 0.6*inch, 1.8*inch, 0.6*inch])
    bh_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), DARK_BLUE),
                                  ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
                                  ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                  ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                  ('FONTSIZE', (0, 0), (-1, -1), 12),
                                  ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
                                  ('ROWBACKGROUNDS', (0, 1), (-1, -1), [CREAM, WHITE])]))
    el.append(bh_table)
    el.append(Spacer(1, 6))
    
    # Comments
    ct = behavior.class_teacher_comment if behavior and behavior.class_teacher_comment else '-'
    am = behavior.academic_master_comment if behavior and behavior.academic_master_comment else '-'
    hs = behavior.head_of_school_comment if behavior and behavior.head_of_school_comment else 'Aongeze bidii zaidi katika masomo yote!'
    
    el.append(Paragraph("<b>OFFICIAL COMMENTS</b>", normal_style))
    el.append(Spacer(1, 3))
    el.append(Paragraph(f"<b>Class Teacher:</b> <u>{ct}</u>", normal_style))
    el.append(Spacer(1, 2))
    el.append(Paragraph(f"<b>Academic Master:</b> <u>{am}</u>", normal_style))
    el.append(Spacer(1, 2))
    el.append(Paragraph(f"<b>Head of School:</b> <u>{hs}</u>", normal_style))
    el.append(Spacer(1, 8))
    
    # Signatures
    sig_data = [['_____________________', '_____________________', '_____________________'],
                ['Class Teacher', 'Academic Master', 'Head of School']]
    sig_table = Table(sig_data, colWidths=[2.3*inch, 2.3*inch, 2.3*inch])
    sig_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('FONTSIZE', (0, 0), (-1, -1), 10)]))
    el.append(sig_table)
    el.append(Spacer(1, 6))
    
    el.append(Paragraph(f"Processed: {datetime.now().strftime('%d/%m/%Y at %H:%M:%S')} | Uchile RMS v1.0", small_style))
    
    doc.build(el)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                    download_name=f'Report_{st.cno}.pdf')

# ==================== NECTA FORMAT PDF ====================
@app.route('/api/reports/necta-format/<int:eid>')
def necta_pdf(eid):
    er = db.session.get(ExamRecord, eid)
    if not er:
        return "Exam record not found", 404
    
    cl = db.session.get(Class, er.class_id)
    level = cl.level
    
    results_student_ids = [r.student_id for r in Result.query.filter_by(exam_record_id=eid).all()]
    students = Student.query.filter(
        (Student.class_id == cl.id) | (Student.id.in_(results_student_ids)),
        Student.is_deleted == False
    ).order_by(Student.cno).all()
    
    subjects = Subject.query.filter_by(level=level).order_by(Subject.code).all()
    
    is_admin = current_user.is_authenticated and current_user.role == 'admin'
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=0.3*inch, rightMargin=0.3*inch,
                           topMargin=0.3*inch, bottomMargin=0.3*inch)
    el = []
    sts = getSampleStyleSheet()
    
    DARK_BLUE = colors.HexColor('#003366')
    MAROON = colors.HexColor('#6B1A3D')
    CREAM = colors.HexColor('#FFF8F0')
    WHITE = colors.white
    PASTEL_BLUE = colors.HexColor('#D4E6F9')
    
    title_style = ParagraphStyle('T', parent=sts['Title'], alignment=TA_CENTER, fontSize=12, textColor=MAROON)
    subtitle_style = ParagraphStyle('ST', parent=sts['Normal'], alignment=TA_CENTER, fontSize=10, textColor=MAROON)
    section_style = ParagraphStyle('SEC', parent=sts['Normal'], alignment=TA_CENTER, fontSize=11, 
                                   textColor=MAROON, fontName='Helvetica-Bold')
    footer_style = ParagraphStyle('F', parent=sts['Normal'], alignment=TA_CENTER, fontSize=8, textColor=MAROON)
    
    header_data = [
        [Paragraph("THE UNITED REPUBLIC OF TANZANIA", title_style)],
        [Paragraph("PRIME MINISTER'S OFFICE - REGIONAL ADMINISTRATION AND LOCAL GOVERNMENT", subtitle_style)],
        [Paragraph("SUMBAWANGA DC - RUKWA REGION", subtitle_style)],
        [Paragraph("UCHILE SECONDARY SCHOOL", title_style)],
        [Paragraph(f"FORM {cl.name} {er.exam_type.upper()} EXAMINATION RESULTS - {er.month} {er.year}", 
                   ParagraphStyle('S3', parent=sts['Normal'], alignment=TA_CENTER, fontSize=10, textColor=MAROON, fontName='Helvetica-Bold'))],
    ]
    header_table = Table(header_data, colWidths=[landscape(A4)[0] - 0.6*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PASTEL_BLUE), ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    el.append(header_table)
    el.append(Spacer(1, 6))
    
    all_results = []
    for stu in students:
        results = Result.query.filter_by(student_id=stu.id, exam_record_id=eid).all()
        is_absent = len(results) == 0
        sd = {'cno': stu.cno, 'sex': stu.sex, 'subjects': {}, 'best_seven_points': 0,
              'core_points': 0, 'division': '', 'num_subjects': 0, 'core_grades': [], 'gpa': 0.0, 'is_absent': is_absent}
        for sj in subjects:
            r = next((x for x in results if x.subject_id == sj.id), None)
            if r:
                sd['subjects'][sj.code] = {'short_code': sj.short_code, 'grade': r.grade, 'points': r.points}
                sd['num_subjects'] += 1; sd['is_absent'] = False
                if level == 'A-LEVEL' and sj.category == 'CORE': sd['core_grades'].append(r.grade)
        if not is_absent:
            if level == 'A-LEVEL':
                sd['gpa'] = calculate_gpa([s['grade'] for s in sd['subjects'].values()], 'A-LEVEL')
                if len(sd['core_grades']) >= 3:
                    sd['core_points'] = sum(calculate_a_level_points(g) for g in sd['core_grades'][:3])
                    sd['division'] = determine_a_level_division(sd['core_grades'][:3])
            else:
                sd['gpa'] = calculate_gpa([s['grade'] for s in sd['subjects'].values()], 'O-LEVEL')
                if sd['num_subjects'] >= 7:
                    all_points = [(subj['points'], code) for code, subj in sd['subjects'].items()]
                    all_points.sort(); sd['best_seven_points'] = sum(p[0] for p in all_points[:7])
                    sd['division'] = determine_o_level_division(sd['best_seven_points'], 7)
        all_results.append(sd)
    
    ds = {'F': {'REGIST': 0, 'ABSENT': 0, 'SAT': 0, 'I': 0, 'II': 0, 'III': 0, 'IV': 0, '0': 0, 'PASSED': 0},
          'M': {'REGIST': 0, 'ABSENT': 0, 'SAT': 0, 'I': 0, 'II': 0, 'III': 0, 'IV': 0, '0': 0, 'PASSED': 0},
          'T': {'REGIST': 0, 'ABSENT': 0, 'SAT': 0, 'I': 0, 'II': 0, 'III': 0, 'IV': 0, '0': 0, 'PASSED': 0}}
    for r in all_results:
        sx = r['sex'].upper() if r['sex'] in ['F', 'M'] else 'M'
        ds[sx]['REGIST'] += 1; ds['T']['REGIST'] += 1
        if r['is_absent']: ds[sx]['ABSENT'] += 1; ds['T']['ABSENT'] += 1
        else:
            ds[sx]['SAT'] += 1; ds['T']['SAT'] += 1
            dv = r['division']
            if dv in ['I', 'II', 'III', 'IV', '0']:
                ds[sx][dv] += 1; ds['T'][dv] += 1
                if dv != '0': ds[sx]['PASSED'] += 1; ds['T']['PASSED'] += 1
    
    sp = {}
    for sj in subjects:
        spd = {'code': sj.code, 'short_code': sj.short_code, 'name': sj.name, 'REG': 0, 'SAT': 0,
               'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0, 'S': 0, 'F': 0, 'PASSED': 0, 'GPA': 0.0,
               'COMPETENCE': '-', 'COMPETENCE_COLOR': PASTEL_BLUE}
        spd['REG'] = StudentSubject.query.filter_by(subject_id=sj.id).join(Student).filter(
            Student.class_id == cl.id, Student.is_deleted == False).count()
        gl = []
        for stu in students:
            r = Result.query.filter_by(student_id=stu.id, subject_id=sj.id, exam_record_id=eid).first()
            if r:
                spd['SAT'] += 1; g = r.grade
                if g in spd: spd[g] += 1
                if level == 'A-LEVEL':
                    if g in ['A', 'B', 'C', 'D', 'E', 'S']: spd['PASSED'] += 1
                else:
                    if g in ['A', 'B', 'C', 'D']: spd['PASSED'] += 1
                gl.append(g)
        if gl:
            spd['GPA'] = calculate_gpa(gl, level); comp, cc = get_competence_status(spd['GPA'], level)
            spd['COMPETENCE'] = comp
            if comp == 'EXCELLENT': spd['COMPETENCE_COLOR'] = colors.HexColor('#006400')
            elif comp == 'VERY GOOD': spd['COMPETENCE_COLOR'] = colors.HexColor('#00AA00')
            elif comp == 'GOOD': spd['COMPETENCE_COLOR'] = colors.HexColor('#FFD700')
            elif comp == 'SATISFACTORY': spd['COMPETENCE_COLOR'] = colors.HexColor('#FF8800')
            elif comp == 'FAIL': spd['COMPETENCE_COLOR'] = colors.HexColor('#FF6666')
        sp[sj.code] = spd
    
    best_subjects = sorted(sp.items(), key=lambda x: x[1]['GPA'] if x[1]['GPA'] > 0 else float('inf'))
    total_passed = ds['T']['PASSED']
    all_gpas = [spd['GPA'] for spd in sp.values() if spd['GPA'] > 0]
    centre_gpa = round(sum(all_gpas) / len(all_gpas), 2) if all_gpas else 0.0
    available_w = landscape(A4)[0] - 0.6*inch
    
    def make_section_title(text):
        t = Table([[Paragraph(text, section_style)]], colWidths=[available_w])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PASTEL_BLUE),
                               ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                               ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
        return t
    
    def make_table_style():
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), DARK_BLUE), ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [CREAM, WHITE]),
            ('TEXTCOLOR', (0, 1), (-1, -1), DARK_BLUE),
        ])
    
    # Section 1
    el.append(make_section_title("1. EXAMINATION CENTRE DIVISION PERFORMANCE SUMMARY"))
    el.append(Spacer(1, 3))
    div_data = [['SEX', 'REGIST', 'ABSENT', 'SAT', 'DIV I', 'DIV II', 'DIV III', 'DIV IV', 'DIV 0', 'PASSED']]
    for sex in ['F', 'M', 'T']:
        div_data.append([sex, str(ds[sex]['REGIST']), str(ds[sex]['ABSENT']), str(ds[sex]['SAT']),
                        str(ds[sex]['I']), str(ds[sex]['II']), str(ds[sex]['III']), str(ds[sex]['IV']),
                        str(ds[sex]['0']), str(ds[sex]['PASSED'])])
    div_table = Table(div_data, colWidths=[available_w/10]*10)
    div_table.setStyle(make_table_style())
    el.append(div_table)
    el.append(Spacer(1, 6))
    
    # Section 2 - Overall Performance
    el.append(make_section_title("2. OVERALL CANDIDATES' PERFORMANCE"))
    el.append(Spacer(1, 3))
    
    if is_admin:
        overall_data = [['CNO', 'FULL NAME', 'SEX', 'AGGT', 'DIV', 'GPA', 'DETAILED SUBJECTS']]
    else:
        overall_data = [['CNO', 'SEX', 'AGGT', 'DIV', 'GPA', 'DETAILED SUBJECTS']]
    
    for r in all_results:
        student = next((s for s in students if s.cno == r['cno']), None)
        full_name = f"{student.first_name} {student.last_name}" if student else ""
        
        if r['is_absent']:
            detailed = ' '.join([f"{s.short_code}-'X'" for s in subjects])
            if is_admin:
                overall_data.append([r['cno'], full_name, r['sex'], 'ABS', '-', '-', detailed])
            else:
                overall_data.append([r['cno'], r['sex'], 'ABS', '-', '-', detailed])
        else:
            agg = r['best_seven_points'] if level == 'O-LEVEL' else r['core_points']
            detailed = ' '.join([f"{r['subjects'][s.code]['short_code']}-'{r['subjects'][s.code]['grade']}'" 
                                if s.code in r['subjects'] else f"{s.short_code}-'X'" for s in subjects])
            if is_admin:
                overall_data.append([r['cno'], full_name, r['sex'], str(agg), r['division'], str(r['gpa']), detailed])
            else:
                overall_data.append([r['cno'], r['sex'], str(agg), r['division'], str(r['gpa']), detailed])
    
    if is_admin:
        overall_table = Table(overall_data, colWidths=[0.7*inch, 2.0*inch, 0.4*inch, 0.5*inch, 0.5*inch, 0.5*inch, available_w - 4.1*inch])
    else:
        overall_table = Table(overall_data, colWidths=[0.8*inch, 0.4*inch, 0.5*inch, 0.5*inch, 0.5*inch, available_w - 4.6*inch])
    
    style_cmds = make_table_style().getCommands()
    style_cmds.append(('ALIGN', (-1, 0), (-1, -1), 'LEFT'))
    style_cmds.append(('ALIGN', (1, 0), (1, -1), 'LEFT'))
    overall_table.setStyle(TableStyle(style_cmds))
    el.append(overall_table)
    el.append(Spacer(1, 6))
    
    # Section 3
    el.append(make_section_title("3. EXAMINATION CENTRE GPA"))
    el.append(Spacer(1, 3))
    gpa_data = [['TOTAL PASSED STUDENTS', str(total_passed)], ['EXAMINATION CENTRE GPA', str(centre_gpa)]]
    gpa_table = Table(gpa_data, colWidths=[available_w*0.5, available_w*0.5])
    gpa_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), DARK_BLUE), ('TEXTCOLOR', (0, 0), (0, -1), WHITE),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10), ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
        ('BACKGROUND', (1, 0), (1, -1), CREAM), ('TEXTCOLOR', (1, 0), (1, -1), DARK_BLUE),
        ('FONTNAME', (1, 1), (1, 1), 'Helvetica-Bold'), ('FONTSIZE', (1, 1), (1, 1), 14),
    ]))
    el.append(gpa_table)
    el.append(Spacer(1, 6))
    
    # Section 4
    el.append(make_section_title("4. DETAILED SUBJECT PERFORMANCE"))
    el.append(Spacer(1, 3))
    subj_headers = ['CODE', 'SUBJECT', 'REG', 'SAT', 'A', 'B', 'C', 'D']
    if level == 'A-LEVEL': subj_headers += ['E', 'S']
    subj_headers += ['F', 'PASSED', 'GPA', 'COMPETENCE']
    subj_data = [subj_headers]
    for code, spd in best_subjects:
        row = [spd['code'], spd['name'], str(spd['REG']), str(spd['SAT']),
               str(spd['A']), str(spd['B']), str(spd['C']), str(spd['D'])]
        if level == 'A-LEVEL': row += [str(spd['E']), str(spd['S'])]
        row += [str(spd['F']), str(spd['PASSED']), str(spd['GPA']), spd['COMPETENCE']]
        subj_data.append(row)
    num_cols = len(subj_headers)
    code_w = available_w * 0.07
    subj_w = available_w * 0.22
    comp_w = available_w * 0.14
    grade_cols = num_cols - 3
    grade_w = (available_w - code_w - subj_w - comp_w) / grade_cols
    widths = [code_w, subj_w]
    for _ in range(grade_cols):
        widths.append(grade_w)
    widths.append(comp_w)
    subj_table = Table(subj_data, colWidths=widths)
    subj_style_cmds = make_table_style().getCommands()
    subj_style_cmds.append(('ALIGN', (1, 0), (1, -1), 'LEFT'))
    style_cmds.append(('FONTSIZE', (-1, 1), (-1, -1), 8))
    comp_col_idx = -1
    for i, (code, spd) in enumerate(best_subjects):
        if spd['COMPETENCE'] != '-':
            subj_style_cmds.append(('BACKGROUND', (comp_col_idx, i+1), (comp_col_idx, i+1), spd['COMPETENCE_COLOR']))
            if spd['COMPETENCE'] in ['FAIL', 'EXCELLENT', 'VERY GOOD', 'SATISFACTORY']:
                subj_style_cmds.append(('TEXTCOLOR', (comp_col_idx, i+1), (comp_col_idx, i+1), WHITE))
            elif spd['COMPETENCE'] == 'GOOD':
                subj_style_cmds.append(('TEXTCOLOR', (comp_col_idx, i+1), (comp_col_idx, i+1), colors.black))
    subj_table.setStyle(TableStyle(subj_style_cmds))
    el.append(subj_table)
    el.append(Spacer(1, 8))
    
    el.append(Paragraph(f"<b>Processed:</b> {datetime.now().strftime('%d/%m/%Y at %H:%M:%S')} | Uchile Results Management System v1.0", footer_style))
    
    doc.build(el)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                    download_name=f'Results_Form{cl.name}_{er.exam_type}_{er.month}_{er.year}.pdf')

@app.route('/api/reports/bulk-report-cards/<int:eid>')
@login_required
@admin_required
def bulk_report_cards(eid):
    er = db.session.get(ExamRecord, eid)
    if not er:
        return "Exam record not found", 404
    
    cl = db.session.get(Class, er.class_id)
    level = cl.level
    students = Student.query.filter_by(class_id=cl.id, is_deleted=False).order_by(Student.cno).all()
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=0.4*inch, rightMargin=0.4*inch,
                           topMargin=0.3*inch, bottomMargin=0.3*inch)
    el = []
    sts = getSampleStyleSheet()
    
    DARK_BLUE = colors.HexColor('#003366')
    CREAM = colors.HexColor('#FFF8F0')
    WHITE = colors.white
    
    title_style = ParagraphStyle('T', parent=sts['Title'], alignment=TA_CENTER, fontSize=16, textColor=WHITE, leading=18)
    subtitle_style = ParagraphStyle('S', parent=sts['Normal'], alignment=TA_CENTER, fontSize=12, textColor=WHITE, leading=14)
    normal_style = ParagraphStyle('N', parent=sts['Normal'], fontSize=12, leading=14)
    small_style = ParagraphStyle('SM', parent=sts['Normal'], fontSize=10, leading=12)
    
    for i, student in enumerate(students):
        if i > 0:
            el.append(PageBreak())
        
        results = Result.query.filter_by(student_id=student.id, exam_record_id=eid).all()
        behavior = Behavior.query.filter_by(student_id=student.id, exam_record_id=eid).first()
        ss = StudentSubject.query.filter_by(student_id=student.id).all()
        
        # Header
        hd = [[Paragraph("UCHILE SECONDARY SCHOOL", title_style)],
              [Paragraph("SUMBAWANGA DC - RUKWA REGION", subtitle_style)],
              [Paragraph(f"FORM {cl.name} - {er.exam_type.upper()} - {er.month} {er.year}", title_style)],
              [Paragraph("STUDENT PROGRESS REPORT", subtitle_style)]]
        ht = Table(hd, colWidths=[A4[0] - 0.8*inch])
        ht.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), DARK_BLUE),
                               ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                               ('TOPPADDING', (0, 0), (-1, -1), 6),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        el.append(ht)
        el.append(Spacer(1, 8))
        
        # Student Info + Passport
        info_text = f"<b>Name:</b> {student.first_name} {student.middle_name or ''} {student.last_name}<br/>"
        info_text += f"<b>CNO:</b> {student.cno}<br/>"
        info_text += f"<b>Admission:</b> {student.admission_number or 'N/A'}<br/>"
        info_text += f"<b>PREM:</b> {student.prem_number or 'N/A'}<br/>"
        info_text += f"<b>Sex:</b> {student.sex}<br/>"
        info_text += f"<b>Class:</b> Form {cl.name}<br/>"
        info_text += f"<b>Combination:</b> {student.combination or 'N/A'}"
        
        info_para = Paragraph(info_text, normal_style)
        
        if student.passport_photo:
            photo_path = student.passport_photo.replace('/uploads/', '')
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_path)
            if os.path.exists(full_path):
                passport_img = Image(full_path, width=100, height=130)
                info_data = [[info_para, passport_img]]
                info_table = Table(info_data, colWidths=[5.5*inch, 1.5*inch])
                info_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
                el.append(info_table)
            else:
                info_data = [[info_para, Paragraph('<b>[PASSPORT<br/>PHOTO]</b>', small_style)]]
                info_table = Table(info_data, colWidths=[5.5*inch, 1.5*inch])
                info_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'CENTER')]))
                el.append(info_table)
        else:
            info_data = [[info_para, Paragraph('<b>[PASSPORT<br/>PHOTO]</b>', small_style)]]
            info_table = Table(info_data, colWidths=[5.5*inch, 1.5*inch])
            info_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'CENTER'), ('BOX', (1, 0), (1, 0), 1, colors.black)]))
            el.append(info_table)
        
        el.append(Spacer(1, 8))
        
        # Results Table
        td = [['CODE', 'SUBJECT', 'SCORE', 'GRADE', 'REMARKS']]
        total_points = 0
        num_subjects = 0
        cg = []
        for s in ss:
            r = next((x for x in results if x.subject_id == s.subject_id), None)
            if r:
                td.append([s.subject.code, s.subject.name, str(r.raw_score), r.grade, 'Pass' if r.grade != 'F' else 'Fail'])
                total_points += r.points
                num_subjects += 1
                if level == 'A-LEVEL' and s.subject.category == 'CORE':
                    cg.append(r.grade)
            else:
                td.append([s.subject.code, s.subject.name, '-', '-', 'Absent'])
        
        cw = [0.6*inch, 3.0*inch, 0.8*inch, 0.7*inch, 1.5*inch]
        t = Table(td, colWidths=cw)
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), DARK_BLUE),
                              ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
                              ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                              ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                              ('FONTSIZE', (0, 0), (-1, 0), 10),
                              ('FONTSIZE', (0, 1), (-1, -1), 10),
                              ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
                              ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                              ('ROWBACKGROUNDS', (0, 1), (-1, -1), [CREAM, WHITE]),
                              ('ALIGN', (1, 0), (1, -1), 'LEFT')]))
        el.append(t)
        el.append(Spacer(1, 6))
        
        # Division & GPA
        if level == 'A-LEVEL' and len(cg) >= 3:
            div = determine_a_level_division(cg[:3])
            pts = sum(calculate_a_level_points(g) for g in cg[:3])
            el.append(Paragraph(f"<b>Division: {div} (Core Points: {pts})</b>", normal_style))
        elif level == 'O-LEVEL' and num_subjects >= 7:
            div = determine_o_level_division(total_points, num_subjects)
            el.append(Paragraph(f"<b>Division: {div} (Total Points: {total_points})</b>", normal_style))
        if results:
            gpa = calculate_gpa([r.grade for r in results], level)
            el.append(Paragraph(f"<b>GPA: {gpa}</b>", normal_style))
        el.append(Paragraph("A=75-100 B=65-74 C=45-64 D=30-44 F=0-29 | A-Level: A=80-100 B=70-79 C=60-69 D=50-59 E=40-49 S=35-39 F=0-34", small_style))
        el.append(Spacer(1, 6))
        
        # Behavior
        el.append(Paragraph("<b>BEHAVIOR & CONDUCT (A=Bora, B=Vizuri, C=Wastani, D=Dhaifu)</b>", normal_style))
        bh_fields = ['heshima', 'ushirikiano', 'kujituma', 'usafi', 'nidhamu', 'uaminifu']
        bh_labels = ['Heshima', 'Ushirikiano', 'Kujituma', 'Usafi', 'Nidhamu', 'Uaminifu']
        bh_data = [['Behavior', 'Grade', 'Behavior', 'Grade']]
        for j in range(0, 6, 2):
            g1 = getattr(behavior, bh_fields[j], '-') if behavior else '-'
            g2 = getattr(behavior, bh_fields[j+1], '-') if behavior else '-'
            bh_data.append([bh_labels[j], g1, bh_labels[j+1], g2])
        bh_table = Table(bh_data, colWidths=[1.8*inch, 0.6*inch, 1.8*inch, 0.6*inch])
        bh_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), DARK_BLUE),
                                      ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
                                      ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                      ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                      ('FONTSIZE', (0, 0), (-1, -1), 12),
                                      ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
                                      ('ROWBACKGROUNDS', (0, 1), (-1, -1), [CREAM, WHITE])]))
        el.append(bh_table)
        el.append(Spacer(1, 6))
        
        # Comments
        ct = behavior.class_teacher_comment if behavior and behavior.class_teacher_comment else '-'
        am = behavior.academic_master_comment if behavior and behavior.academic_master_comment else '-'
        hs = behavior.head_of_school_comment if behavior and behavior.head_of_school_comment else 'Aongeze bidii zaidi katika masomo yote!'
        
        el.append(Paragraph("<b>OFFICIAL COMMENTS</b>", normal_style))
        el.append(Spacer(1, 3))
        el.append(Paragraph(f"<b>Class Teacher:</b> <u>{ct}</u>", normal_style))
        el.append(Spacer(1, 2))
        el.append(Paragraph(f"<b>Academic Master:</b> <u>{am}</u>", normal_style))
        el.append(Spacer(1, 2))
        el.append(Paragraph(f"<b>Head of School:</b> <u>{hs}</u>", normal_style))
        el.append(Spacer(1, 6))
        
        # Signatures
        sig_data = [['_____________________', '_____________________', '_____________________'],
                    ['Class Teacher', 'Academic Master', 'Head of School']]
        sig_table = Table(sig_data, colWidths=[2.3*inch, 2.3*inch, 2.3*inch])
        sig_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('FONTSIZE', (0, 0), (-1, -1), 10)]))
        el.append(sig_table)
        el.append(Spacer(1, 4))
        
        el.append(Paragraph(f"Processed: {datetime.now().strftime('%d/%m/%Y')} | Uchile RMS v1.0", small_style))
    
    doc.build(el)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                    download_name=f'Bulk_Reports_Form{cl.name}_{er.exam_type}.pdf')

# ==================== REGISTRY ====================
@app.route('/registry')
@login_required
@admin_required
def registry_page():
    c = Class.query.order_by(Class.name).all()
    sid = request.args.get('class_id', type=int)
    
    if sid:
        st = Student.query.filter_by(class_id=sid, is_deleted=False).order_by(Student.cno).all()
        sc = db.session.get(Class, sid)
        if sc:
            if sc.curriculum == 'OLD':
                # Show Old Curriculum subjects only
                old_codes = OLD_CURRICULUM_CONFIG['compulsory'] + OLD_CURRICULUM_CONFIG['optional']
                sj = Subject.query.filter(Subject.code.in_(old_codes)).order_by(Subject.code).all()
            else:
                sj = Subject.query.filter_by(level=sc.level).order_by(Subject.code).all()
        else:
            sj = []
    else:
        st = []
        sc = None
        sj = []
    
    rd = []
    for s in st:
        student_subjects = StudentSubject.query.filter_by(student_id=s.id).all()
        registered_codes = [ss.subject.code for ss in student_subjects]
        student_class = db.session.get(Class, s.class_id) if s.class_id else None
        
        rd.append({
            'student': s,
            'student_class': student_class,
            'subject_ticks': {subj.code: subj.code in registered_codes for subj in sj},
            'total_subjects': len(registered_codes)
        })
    
    return render_template('registry.html', classes=c, subjects=sj, registry_data=rd,
                           selected_class=sc, selected_class_id=sid)
@app.route('/api/registry/pdf')
@login_required
@admin_required
def registry_pdf():
    sid = request.args.get('class_id', type=int)
    
    if sid:
        students = Student.query.filter_by(class_id=sid, is_deleted=False).order_by(Student.cno).all()
        cl = db.session.get(Class, sid)
        if cl:
            title = f"STUDENT REGISTRY - FORM {cl.name}"
            level = cl.level
        else:
            title = "STUDENT REGISTRY"
            level = 'O-LEVEL'
        subtitle = "UCHILE SECONDARY SCHOOL - SUMBAWANGA DC, RUKWA"
        subjects = Subject.query.filter_by(level=level).order_by(Subject.code).all()
    else:
        students = Student.query.filter_by(is_deleted=False).order_by(Student.class_id, Student.cno).all()
        cl = None
        title = "STUDENT REGISTRY - ALL CLASSES"
        subtitle = "UCHILE SECONDARY SCHOOL - SUMBAWANGA DC, RUKWA"
        subjects = Subject.query.order_by(Subject.code).all()
    
    if not students:
        return "No students found for this selection.", 404
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=0.3*inch, rightMargin=0.3*inch,
                           topMargin=0.3*inch, bottomMargin=0.3*inch)
    el = []
    sts = getSampleStyleSheet()
    
    DARK_BLUE = colors.HexColor('#003366')
    WHITE = colors.white
    CREAM = colors.HexColor('#FFF8F0')
    
    title_style = ParagraphStyle('T', parent=sts['Title'], alignment=TA_CENTER, fontSize=14, textColor=WHITE, leading=16)
    subtitle_style = ParagraphStyle('S', parent=sts['Normal'], alignment=TA_CENTER, fontSize=10, textColor=WHITE, leading=12)
    header_style = ParagraphStyle('H', parent=sts['Normal'], alignment=TA_CENTER, fontSize=7, textColor=WHITE, leading=9)
    footer_style = ParagraphStyle('F', parent=sts['Normal'], alignment=TA_CENTER, fontSize=8, leading=10)
    
    # Header
    header_data = [[Paragraph(title, title_style)], [Paragraph(subtitle, subtitle_style)]]
    header_table = Table(header_data, colWidths=[landscape(A4)[0] - 0.6*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), DARK_BLUE),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    el.append(header_table)
    el.append(Spacer(1, 8))
    
    # Table
    table_headers = ['S/N', 'CNO', 'FULL NAME', 'SEX']
    if not sid:
        table_headers.insert(4, 'CLASS')
    for s in subjects:
        table_headers.append(Paragraph(s.short_code, header_style))
    
    table_data = [table_headers]
    for i, student in enumerate(students):
        ss_list = StudentSubject.query.filter_by(student_id=student.id).all()
        codes = [ss.subject.code for ss in ss_list]
        student_class = db.session.get(Class, student.class_id) if student.class_id else None
        class_name = f"Form {student_class.name}" if student_class else 'N/A'
        
        row = [str(i+1), student.cno, f"{student.first_name} {student.last_name}", student.sex]
        if not sid:
            row.insert(4, class_name)
        
        for subj in subjects:
            if subj.code in codes:
                row.append(Paragraph('<b><font color="green">✓</font></b>', header_style))
            else:
                row.append(Paragraph('-', header_style))
        table_data.append(row)
    
    col_widths = [0.4*inch, 1.0*inch, 2.5*inch, 0.4*inch]
    if not sid:
        col_widths.insert(4, 0.7*inch)
    for _ in subjects:
        col_widths.append(0.45*inch)
    
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), DARK_BLUE),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), CREAM))
    t.setStyle(TableStyle(style_cmds))
    el.append(t)
    el.append(Spacer(1, 10))
    
    # Summary
    male_count = sum(1 for s in students if s.sex == 'M')
    female_count = sum(1 for s in students if s.sex == 'F')
    summary_style = ParagraphStyle('Sum', parent=sts['Normal'], fontSize=10, alignment=TA_CENTER)
    el.append(Paragraph(f"<b>TOTAL STUDENTS: {len(students)} | MALE: {male_count} | FEMALE: {female_count}</b>", summary_style))
    el.append(Spacer(1, 8))
    el.append(Paragraph(f"<b>Processed:</b> {datetime.now().strftime('%d/%m/%Y at %H:%M:%S')}", footer_style))
    el.append(Paragraph("Uchile Results Management System v1.0", footer_style))
    
    doc.build(el)
    buf.seek(0)
    
    filename = f'Registry_Form{cl.name}' if cl else 'Registry_All_Classes'
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=f'{filename}.pdf')

# ==================== PUBLIC ROUTES ====================
@app.route('/public/results')
def public_results():
    return redirect(url_for('login'))

@app.route('/api/public/classes')
def public_classes():
    classes = Class.query.order_by(Class.name).all()
    return jsonify([{'id': c.id, 'name': c.name, 'level': c.level} for c in classes])

@app.route('/api/public/exam-types/<int:class_id>')
def public_exam_types(class_id):
    exams = ExamRecord.query.filter_by(class_id=class_id).order_by(ExamRecord.created_at.desc()).all()
    return jsonify([{'exam_type': e.exam_type, 'month': e.month, 'year': e.year} for e in exams])

@app.route('/api/public/find-exam')
def public_find_exam():
    class_id = request.args.get('class_id', type=int)
    exam_type = request.args.get('exam_type', '')
    month = request.args.get('month', '')
    year = request.args.get('year', type=int)
    exam = ExamRecord.query.filter_by(class_id=class_id, exam_type=exam_type, month=month, year=year).first()
    if exam:
        return jsonify({'exam_record_id': exam.id})
    return jsonify({'exam_record_id': None})

# ==================== HELPER ROUTES ====================
@app.route('/api/class-students/<int:class_id>')
@login_required
@admin_required
def get_class_students(class_id):
    students = Student.query.filter_by(class_id=class_id, is_deleted=False).order_by(Student.admission_number).all()
    return jsonify([{'id': s.id, 'admission_number': s.admission_number,
                     'first_name': s.first_name, 'last_name': s.last_name} for s in students])
@app.route('/api/class-info/<int:class_id>')
@login_required
@admin_required
def get_class_info(class_id):
    cl = db.session.get(Class, class_id)
    if cl:
        return jsonify({'id': cl.id, 'name': cl.name, 'level': cl.level, 'curriculum': cl.curriculum or 'NEW'})
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/reports/division-summary')
@login_required
@admin_required
def division_summary_report():
    class_id = request.args.get('class_id', type=int)
    exam_type = request.args.get('exam_type', '')
    cl = db.session.get(Class, class_id)
    if not cl:
        return "Class not found", 404
    level = cl.level
    students = Student.query.filter_by(class_id=class_id, is_deleted=False).order_by(Student.admission_number).all()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=0.5*inch, rightMargin=0.5*inch,
                           topMargin=0.4*inch, bottomMargin=0.4*inch)
    el = []
    sts = getSampleStyleSheet()
    ts = ParagraphStyle('T', parent=sts['Title'], alignment=TA_CENTER, fontSize=14, textColor=colors.white)
    ss = ParagraphStyle('S', parent=sts['Normal'], alignment=TA_CENTER, fontSize=10)
    ns = ParagraphStyle('N', parent=sts['Normal'], fontSize=9)
    hd = [[Paragraph("UCHILE SECONDARY SCHOOL", ts)],
          [Paragraph("DIVISION PERFORMANCE SUMMARY", ts)],
          [Paragraph(f"Form {cl.name} - {exam_type} - {datetime.now().strftime('%B %Y')}", ss)]]
    ht = Table(hd, colWidths=[A4[0] - 1*inch])
    ht.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#003366')),
                           ('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
    el.append(ht)
    el.append(Spacer(1, 15))
    div_counts = {'I': 0, 'II': 0, 'III': 0, 'IV': 0, '0': 0}
    absent = 0
    for stu in students:
        results = Result.query.join(ExamRecord).filter(
            Result.student_id == stu.id, ExamRecord.class_id == class_id,
            ExamRecord.exam_type == exam_type).all()
        if not results:
            absent += 1
        else:
            if level == 'A-LEVEL':
                core_gr = [r.grade for r in results if r.subject.category == 'CORE']
                if len(core_gr) >= 3:
                    div = determine_a_level_division(core_gr[:3])
                else:
                    div = 'INCOMPLETE'
            else:
                if len(results) >= 7:
                    pts = sorted([r.points for r in results])[:7]
                    div = determine_o_level_division(sum(pts), 7)
                else:
                    div = 'INCOMPLETE'
            if div in div_counts:
                div_counts[div] += 1
    td = [['REGIST', 'ABSENT', 'SAT', 'DIV I', 'DIV II', 'DIV III', 'DIV IV', 'DIV 0', 'PASSED']]
    sat = len(students) - absent
    passed = sum(div_counts[d] for d in ['I', 'II', 'III', 'IV'])
    td.append([str(len(students)), str(absent), str(sat), str(div_counts['I']), str(div_counts['II']),
              str(div_counts['III']), str(div_counts['IV']), str(div_counts['0']), str(passed)])
    t = Table(td, colWidths=[1*inch] * 9)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
                          ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                          ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                          ('GRID', (0, 0), (-1, -1), 0.5, colors.black)]))
    el.append(t)
    el.append(Spacer(1, 15))
    el.append(Paragraph(f"Processed: {datetime.now().strftime('%d/%m/%Y at %H:%M:%S')}", ns))
    doc.build(el)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                    download_name=f'Division_Summary_Form{cl.name}_{exam_type}.pdf')

@app.route('/api/download/template/<tt>')
@login_required
@admin_required
def download_template(tt):
    if tt == 'students':
        df = pd.DataFrame(columns=['cno', 'admission_number', 'prem_number', 'first_name', 'middle_name', 'last_name', 'sex'])
    elif tt == 'scores':
        class_id = request.args.get('class_id', type=int)
        if class_id:
            cl = db.session.get(Class, class_id)
            if cl:
                students = Student.query.filter_by(class_id=class_id, is_deleted=False).order_by(Student.cno).all()
                subjects = Subject.query.filter_by(level=cl.level).order_by(Subject.code).all()
                data = {'cno': [], 'student_name': []}
                for subject in subjects:
                    data[f"{subject.code} {subject.name}"] = []
                for student in students:
                    data['cno'].append(student.cno)
                    data['student_name'].append(f"{student.first_name} {student.last_name}")
                    for subject in subjects:
                        data[f"{subject.code} {subject.name}"].append('')
                df = pd.DataFrame(data)
            else:
                df = pd.DataFrame(columns=['cno', 'student_name'])
        else:
            df = pd.DataFrame(columns=['cno', 'student_name'])
    else:
        return jsonify({'error': 'Invalid template'}), 400
    
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Template')
    buf.seek(0)
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    as_attachment=True, download_name=f'{tt}_template.xlsx')

# ==================== PASSWORD MANAGEMENT ====================
def validate_password_strength(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*(),.?\":{}|<>]', password):
        return False, "Password must contain at least one special character"
    return True, "Password is strong"
        

@app.route('/api/change-password', methods=['POST'])
@login_required
@admin_required
def change_password():
    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')
    if not current_password or not new_password or not confirm_password:
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    if new_password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400
    is_valid, msg = validate_password_strength(new_password)
    if not is_valid:
        return jsonify({'success': False, 'message': msg}), 400
    if not current_user.check_password(current_password):
        return jsonify({'success': False, 'message': 'Current password is incorrect'}), 400
    current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password changed successfully!'})

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    email = request.get_json().get('email', '')
    user = User.query.filter_by(email=email).first()
    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        send_reset_email(email, token)
    return jsonify({'success': True, 'message': 'If the email exists, a reset link has been sent.'})

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        flash('Invalid or expired reset link.', 'danger')
        return redirect(url_for('login'))
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)
        is_valid, msg = validate_password_strength(new_password)
        if not is_valid:
            flash(msg, 'danger')
            return render_template('reset_password.html', token=token)
        user.set_password(new_password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        flash('Password reset successfully!', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)

def get_auto_comments(division):
    """Get auto-comments based on division - Swahili"""
    comments = {
        'I': {
            'class_teacher': 'Bora sana! Aongeze bidii!',
            'academic_master': 'Vizuri sana! Asibweteke!'
        },
        'II': {
            'class_teacher': 'Vizuri! Aongeze bidii zaidi!',
            'academic_master': 'Vizuri! Akazane zaidi!'
        },
        'III': {
            'class_teacher': 'Wastani! Aongeze bidii zaidi!',
            'academic_master': 'Wastani! Aongeze bidii zaidi katika masomo yote!'
        },
        'IV': {
            'class_teacher': 'Dhaifu! Ajitahidi kujisomea!',
            'academic_master': 'Dhaifu! Aongeze bidii zaidi katika masomo yote!'
        },
        '0': {
            'class_teacher': 'Mbaya! Ajitahidi kujisomea!',
            'academic_master': 'Mbaya! Aongeze bidii zaidi katika masomo yote!'
        },
        'ABS': {
            'class_teacher': 'Hakufanya mtihani.',
            'academic_master': 'Hakufanya mtihani.'
        }
    }
    return comments.get(division, {'class_teacher': '', 'academic_master': ''})

@app.route('/teacher/students')
@login_required
def teacher_students():
    if current_user.role not in ['admin', 'teacher']:
        abort(403)
    classes = Class.query.order_by(Class.name).all()
    exam_records = ExamRecord.query.order_by(ExamRecord.created_at.desc()).all()
    selected_class_id = request.args.get('class_id', type=int)
    selected_exam_id = request.args.get('exam_id', type=int)
    students = []
    if selected_class_id and selected_exam_id:
        students = Student.query.filter_by(class_id=selected_class_id, is_deleted=False).order_by(Student.admission_number).all()
    return render_template('teacher_students.html', classes=classes, exam_records=exam_records,
                         students=students, selected_class_id=selected_class_id, selected_exam_id=selected_exam_id)

@app.route('/api/behavior/save', methods=['POST'])
@login_required
def save_behavior():
    if current_user.role not in ['admin', 'teacher']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        exam_record_id = data.get('exam_record_id')
        behavior = Behavior.query.filter_by(student_id=student_id, exam_record_id=exam_record_id).first()
        if not behavior:
            behavior = Behavior(student_id=student_id, exam_record_id=exam_record_id)
            db.session.add(behavior)
        behavior.heshima = data.get('heshima', 'B')
        behavior.ushirikiano = data.get('ushirikiano', 'B')
        behavior.kujituma = data.get('kujituma', 'B')
        behavior.usafi = data.get('usafi', 'B')
        behavior.nidhamu = data.get('nidhamu', 'B')
        behavior.uaminifu = data.get('uaminifu', 'B')
        results = Result.query.filter_by(student_id=student_id, exam_record_id=exam_record_id).all()
        if results:
            er = db.session.get(ExamRecord, exam_record_id)
            cl = db.session.get(Class, er.class_id)
            level = cl.level
            if level == 'A-LEVEL':
                cg = [r.grade for r in results if r.subject.category == 'CORE']
                div = determine_a_level_division(cg[:3]) if len(cg) >= 3 else 'ABS'
            else:
                if len(results) >= 7:
                    pts = sorted([r.points for r in results])[:7]
                    div = determine_o_level_division(sum(pts), 7)
                else:
                    div = 'ABS'
        else:
            div = 'ABS'
        comments = get_auto_comments(div)
        behavior.class_teacher_comment = comments['class_teacher']
        behavior.academic_master_comment = comments['academic_master']
        behavior.head_of_school_comment = 'Aongeze bidii zaidi katika masomo yote!'
        print(f"DEBUG: Saving comments for student {student_id}: CT={comments['class_teacher']}, AM={comments['academic_master']}, Div={div}")
    
        db.session.commit()
        return jsonify({'success': True, 'message': 'Behavior saved!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/students/promote', methods=['POST'])
@login_required
@admin_required
def promote_students():
    try:
        data = request.get_json()
        exam_record_id = data.get('exam_record_id')
        
        er = db.session.get(ExamRecord, exam_record_id)
        if not er:
            return jsonify({'success': False, 'message': 'Exam record not found'}), 404
        
        if er.exam_type != 'ANNUAL':
            return jsonify({'success': False, 'message': 'Only ANNUAL exams can be used for promotion'}), 400
        
        cl = db.session.get(Class, er.class_id)
        current_form = int(cl.name)
        level = cl.level
        
        if (level == 'O-LEVEL' and current_form == 4) or (level == 'A-LEVEL' and current_form == 6):
            students = Student.query.filter_by(class_id=cl.id, is_deleted=False).all()
            for s in students:
                s.is_active = False
                # Record in history
                ph = PromotionHistory(student_id=s.id, from_class_id=cl.id, to_class_id=0, 
                                     exam_record_id=exam_record_id, promoted_by=current_user.id)
                db.session.add(ph)
            db.session.commit()
            return jsonify({'success': True, 'message': f'{len(students)} students graduated!'})
        
        next_form = current_form + 1
        next_level = 'O-LEVEL' if next_form <= 4 else 'A-LEVEL'
        next_class = Class.query.filter_by(name=str(next_form), level=next_level).first()
        
        if not next_class:
            next_class = Class(name=str(next_form), level=next_level)
            db.session.add(next_class)
            db.session.flush()
        
        students = Student.query.filter_by(class_id=cl.id, is_deleted=False).all()
        promoted = 0
        for s in students:
            old_class_id = s.class_id
            s.class_id = next_class.id
            promoted += 1
            # Record in history
            ph = PromotionHistory(student_id=s.id, from_class_id=old_class_id, to_class_id=next_class.id,
                                 exam_record_id=exam_record_id, promoted_by=current_user.id)
            db.session.add(ph)
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'{promoted} students promoted from Form {current_form} to Form {next_form}!',
                       'promotion_count': promoted, 'from_class': current_form, 'to_class': next_form})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/students/rollback-promotion', methods=['POST'])
@login_required
@admin_required
def rollback_promotion():
    try:
        data = request.get_json()
        exam_record_id = data.get('exam_record_id')
        
        # Get all promotions for this exam that haven't been rolled back
        promotions = PromotionHistory.query.filter_by(
            exam_record_id=exam_record_id, is_rolled_back=False
        ).all()
        
        if not promotions:
            return jsonify({'success': False, 'message': 'No promotions found for this exam'}), 404
        
        rolled_back = 0
        for ph in promotions:
            student = db.session.get(Student, ph.student_id)
            if student and ph.to_class_id != 0:  # Not graduated
                student.class_id = ph.from_class_id
                student.is_active = True
            ph.is_rolled_back = True
            rolled_back += 1
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'{rolled_back} students rolled back!'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/students/selective-rollback', methods=['POST'])
@login_required
@admin_required
def selective_rollback():
    try:
        data = request.get_json()
        student_ids = data.get('student_ids', [])
        
        rolled_back = 0
        for sid in student_ids:
            ph = PromotionHistory.query.filter_by(
                student_id=sid, is_rolled_back=False
            ).order_by(PromotionHistory.promoted_at.desc()).first()
            
            if ph and ph.to_class_id != 0:
                student = db.session.get(Student, sid)
                if student:
                    student.class_id = ph.from_class_id
                    student.is_active = True
                    ph.is_rolled_back = True
                    rolled_back += 1
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'{rolled_back} students rolled back!'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/students/print-list')
@login_required
@admin_required
def print_student_list():
    class_id = request.args.get('class_id', type=int)
    
    if class_id:
        students = Student.query.filter_by(class_id=class_id, is_deleted=False).order_by(Student.cno).all()
        cl = db.session.get(Class, class_id)
        title = f"STUDENT LIST - FORM {cl.name}" if cl else "STUDENT LIST"
    else:
        students = Student.query.filter_by(is_deleted=False).order_by(Student.class_id, Student.cno).all()
        title = "STUDENT LIST - ALL CLASSES"
    
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=0.3*inch, rightMargin=0.3*inch,
                           topMargin=0.3*inch, bottomMargin=0.3*inch)
    el = []
    sts = getSampleStyleSheet()
    ts = ParagraphStyle('T', parent=sts['Title'], alignment=TA_CENTER, fontSize=14, textColor=colors.HexColor('#6B1A3D'))
    
    el.append(Paragraph("UCHILE SECONDARY SCHOOL", ts))
    el.append(Paragraph(title, ts))
    el.append(Spacer(1, 10))
    
    td = [['S/N', 'CNO', 'ADM NO', 'FULL NAME', 'SEX', 'CLASS']]
    for i, s in enumerate(students):
        sc = db.session.get(Class, s.class_id) if s.class_id else None
        class_name = f"Form {sc.name}" if sc else 'N/A'
        td.append([str(i+1), s.cno, s.admission_number or '-', 
                   f"{s.first_name} {s.middle_name or ''} {s.last_name}", s.sex, class_name])
    
    t = Table(td, colWidths=[0.5*inch, 1.5*inch, 1.5*inch, 3.5*inch, 0.6*inch, 1.2*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003366')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    el.append(t)
    el.append(Spacer(1, 10))
    el.append(Paragraph(f"Total: {len(students)} students | {datetime.now().strftime('%d/%m/%Y %H:%M')}", 
                        ParagraphStyle('F', parent=sts['Normal'], fontSize=9)))
    doc.build(el)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='Student_List.pdf')

def log_action(action, details=''):
    """Record user actions for audit"""
    if current_user.is_authenticated:
        log = AuditLog(
            user_id=current_user.id,
            action=action,
            details=str(details),
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()

# ==================== INITIALIZATION ====================
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            u = User(username='admin', email='admin@uchile.sc.tz', role='admin', full_name='Head of School')
            u.set_password('admin123')
            db.session.add(u)
        if not User.query.filter_by(username='teacher').first():
            t = User(username='teacher', email='teacher@uchile.sc.tz', role='teacher', full_name='Class Teacher')
            t.set_password('teacher123')
            db.session.add(t)
        for i in range(1, 7):
            lv = 'O-LEVEL' if i <= 4 else 'A-LEVEL'
            if not Class.query.filter_by(name=str(i), level=lv).first():
                db.session.add(Class(name=str(i), level=lv))
        db.session.commit()
        
        # Set Form III & IV to Old Curriculum by default
        for i in [3, 4]:
            c = Class.query.filter_by(name=str(i), level='O-LEVEL').first()
            if c and not c.curriculum:
                c.curriculum = 'OLD'
        db.session.commit()
        for code, info in O_LEVEL_SUBJECTS.items():
            if not Subject.query.filter_by(code=code).first():
                db.session.add(Subject(name=info['name'], code=code, short_code=info['short'],
                                      level='O-LEVEL', category=info['category']))
        for code, info in A_LEVEL_SUBJECTS.items():
            if not Subject.query.filter_by(code=code).first():
                db.session.add(Subject(name=info['name'], code=code, short_code=info['short'],
                                      level='A-LEVEL', category=info['category']))
        for code, info in O_LEVEL_SUBJECTS.items():
            if not Subject.query.filter_by(code=code).first():
                db.session.add(Subject(name=info['name'], code=code, short_code=info['short'],
                                      level='O-LEVEL', category=info['category']))
        for code, info in A_LEVEL_SUBJECTS.items():
            if not Subject.query.filter_by(code=code).first():
                db.session.add(Subject(name=info['name'], code=code, short_code=info['short'],
                                      level='A-LEVEL', category=info['category']))
        
        # Add Old Curriculum subjects
        if not Subject.query.filter_by(code='201').first():
            db.session.add(Subject(name='CIVICS', code='201', short_code='CIV', level='O-LEVEL', category='COMPULSORY'))
        if not Subject.query.filter_by(code='024').first():
            db.session.add(Subject(name='LITERATURE IN ENGLISH', code='024', short_code='LIT', level='O-LEVEL', category='OPTIONAL'))
        
        db.session.commit()

# Initialize database before first request
@app.before_request
def initialize():
    init_db()

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)