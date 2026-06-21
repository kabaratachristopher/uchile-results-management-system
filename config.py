import os

class Config:
    SYSTEM_NAME = 'Uchile Results Management System'
    SYSTEM_VERSION = '1.0.0'
    SCHOOL_NAME = 'UCHILE SECONDARY SCHOOL'
    SCHOOL_ADDRESS = 'SUMBAWANGA DC - RUKWA REGION'
    
    SECRET_KEY = os.environ.get('SECRET_KEY', 'uchile-results-secret-key-2024')
    
    basedir = os.path.abspath(os.path.dirname(__file__))
    
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        SQLALCHEMY_DATABASE_URI = database_url
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'uchile_results.db')
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    
    # Email Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_USERNAME', '')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@uchile.sc.tz')