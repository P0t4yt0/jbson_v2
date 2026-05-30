import os
from datetime import datetime
from django.shortcuts import render, redirect
from django.db import connection
from django.contrib import messages
from django.http import FileResponse
from django.core.management import call_command
from django.conf import settings
from django.core.files.storage import FileSystemStorage

# 🟢 SIGURADUHING NAKA-IMPORT ITO
from activity_log.utils import log_system_activity

# ==========================================
# HELPER FUNCTIONS
# ==========================================

# Helper para sa Database Size
def get_current_db_size():
    with connection.cursor() as cursor:
        cursor.execute("SELECT round(sum(data_length + index_length) / 1024 / 1024, 2) FROM information_schema.tables WHERE table_schema = 'jbson_dev';")
        result = cursor.fetchone()
        return result[0] if result and result[0] else 0

# Helper para sa Last Backup Time
def get_last_backup_time():
    backup_dir = os.path.join(settings.BASE_DIR, 'secure_backups')
    if not os.path.exists(backup_dir):
        return "No backups yet"
    
    files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(('.gz', '.sqlite3', '.sql'))]
    if not files:
        return "No backups yet"
        
    latest_file = max(files, key=os.path.getctime)
    dt_object = datetime.fromtimestamp(os.path.getctime(latest_file))
    return dt_object.strftime("%B %d, %Y - %I:%M %p")

# Main View
def maintenance_dashboard(request):
    # 1. RUN DIAGNOSTICS (Scan)
    report = []
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLE STATUS WHERE Data_free > 0")
        tables = cursor.fetchall()
        for table in tables:
            overhead_mb = round(table[11] / 1024 / 1024, 3)
            report.append(f"Table '{table[0]}' has {overhead_mb} MB overhead.")

    # 2. POST ACTION (Clean/Optimize)
    if request.method == "POST":
        if report: # I-optimize lang kung may nakitang overhead
            with connection.cursor() as cursor:
                cursor.execute("OPTIMIZE TABLE inventory_product, pointofsale_transaction, security_activitylog")
            
            # 🟢 LOG ACTIVITY: SYSTEM MAINTENANCE
            log_system_activity(
                user=request.user,
                action="SYSTEM MAINTENANCE",
                description="Executed database optimization to clear overhead."
            )
            messages.success(request, "Database successfully optimized!")
        else:
            messages.info(request, "Database is already optimized. No action needed.")
        return redirect(request.path)

    # 3. RENDER
    context = {
        'db_size': get_current_db_size(),
        'report': report,
        'last_backup_time': get_last_backup_time(),
    }
    
    return render(request, 'dashboard/settings_hub.html', context)


# ==========================================
# BACKUP, RESTORE, AND DELETE VIEWS
# ==========================================

def trigger_backup(request):
    if request.method == 'POST':
        try:
            call_command('backup_db')
            
            backup_dir = os.path.join(settings.BASE_DIR, 'secure_backups')
            files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir)]
            latest_file = max(files, key=os.path.getctime)
            
            # 🟢 LOG ACTIVITY: DATABASE BACKUP (nasa loob ng try block)
            log_system_activity(
                user=request.user,
                action="DATABASE BACKUP",
                description="Successfully generated and downloaded a manual database backup."
            )
            
            response = FileResponse(open(latest_file, 'rb'), as_attachment=True)
            return response
            
        except Exception as e:
            messages.error(request, f'Backup failed: {e}')
            return redirect(request.META.get('HTTP_REFERER', '/'))

def trigger_restore(request):
    if request.method == 'POST' and request.FILES.get('backup_file'):
        uploaded_file = request.FILES['backup_file']
        fs = FileSystemStorage(location=os.path.join(settings.BASE_DIR, 'secure_backups'))
        
        filename = fs.save(uploaded_file.name, uploaded_file)
        filepath = fs.path(filename)
        
        try:
            call_command('restore_db', filepath)
            
            # 🟢 LOG ACTIVITY: DATABASE RESTORE (nasa loob ng try block)
            log_system_activity(
                user=request.user,
                action="DATABASE RESTORE",
                description=f"Restored the database using backup file: '{uploaded_file.name}'."
            )
            
            messages.success(request, 'System successfully restored!')
        except Exception as e:
            messages.error(request, f'Restore failed: {e}')
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
                
        # HTTP_REFERER para bumalik sa settings page
        return redirect(request.META.get('HTTP_REFERER', '/'))

def delete_all_data(request):
    if request.method == 'POST':
        # 1. Tables na HINDI dapat mabura (Credentials & System Core)
        protected_tables = [
            'auth_user', 
            'auth_group', 
            'auth_permission', 
            'auth_user_groups', 
            'auth_user_user_permissions', 
            'django_migrations',
            'django_content_type',
            'django_session',
            'django_admin_log'
        ]

        try:
            with connection.cursor() as cursor:
                # Kunin ang lahat ng tables sa database
                cursor.execute("SHOW TABLES")
                all_tables = [row[0] for row in cursor.fetchall()]

                # I-disable ang foreign key checks para hindi mag-error
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
                
                for table in all_tables:
                    if table not in protected_tables:
                        # Dito natin buburahin lahat ng DATA (TRUNCATE)
                        # Pero hindi mabubura ang structure ng table
                        cursor.execute(f"TRUNCATE TABLE {table};")
                
                # I-enable ulit ang foreign key checks
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

            # 🟢 LOG ACTIVITY: WIPE DATA (nasa loob ng try block)
            log_system_activity(
                user=request.user,
                action="SYSTEM WIPE",
                description="Performed a full system wipe (Truncate). All transactions and configurations were cleared."
            )

            messages.success(request, 'System wiped! All transactions cleared but credentials remain.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
             
    return redirect(request.META.get('HTTP_REFERER', '/'))