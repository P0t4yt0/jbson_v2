from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'django-insecure-jbson-hardware-pms-2025-change-in-production'
DEBUG = True
ALLOWED_HOSTS = ['*']
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'security','inventory','product_registration','point_of_sale',
    'billing_payment','reports_analytics','activity_log',
    'notifications','maintenance','search','user_manual',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'jbson_pms.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'jbson_pms.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'jbson_dev',               # Matches your DBeaver database name
        'USER': 'root',                   # Change to 'root' unless you made a specific 'jbson_user'
        'PASSWORD': 'January152005', # Put your MySQL Workbench/DBeaver password here
        'HOST': 'localhost',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"
        }
    }
}

# MySQL 8.4 Production (uncomment when deploying on LAN):
# DATABASES = {'default':{'ENGINE':'django.db.backends.mysql','NAME':'jbson_db','USER':'jbson_user','PASSWORD':'your_password','HOST':'localhost','PORT':'3306','OPTIONS':{'charset':'utf8mb4','init_command':"SET sql_mode='STRICT_TRANS_TABLES'"}}}
AUTH_USER_MODEL = 'security.User'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.BCryptSHA256PasswordHasher','django.contrib.auth.hashers.PBKDF2PasswordHasher']
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/auth/login/'
SESSION_COOKIE_AGE = 28800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
ABC_A_THRESHOLD = 0.70
ABC_B_THRESHOLD = 0.90
BACKUP_DIR = BASE_DIR / 'backups'
AUTO_BACKUP_HOUR = 22
