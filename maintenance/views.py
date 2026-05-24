import os
from django.shortcuts import render, redirect
from django.db import connection
from django.contrib import messages
from django.http import FileResponse
from django.core.management import call_command
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from datetime import datetime

# Helper function para sa DB Size
def get_current_db_size():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT round(sum(data_length + index_length) / 1024 / 1024, 2) 
            FROM information_schema.tables 
            WHERE table_schema = 'jbson_dev';
        """)
        result = cursor.fetchone()
        return result[0] if result and result[0] else 0

# PINAG-ISANG DASHBOARD VIEW
def maintenance_dashboard(request):
    # 1. RUN DIAGNOSTICS (Scan)
    report = []
    with connection.cursor() as cursor:
        # Check tables with fragmentation/overhead
        cursor.execute("SHOW TABLE STATUS WHERE Data_free > 0")
        tables = cursor.fetchall()
        for table in tables:
            # table[0] = table name, table[11] = Data_free (overhead)
            overhead_mb = round(table[11] / 1024 / 1024, 3)
            report.append(f"Table '{table[0]}' has {overhead_mb} MB overhead.")

    # 2. POST ACTION (Clean/Optimize)
    if request.method == "POST":
        with connection.cursor() as cursor:
            # Optimizing key tables
            cursor.execute("OPTIMIZE TABLE inventory_product, pointofsale_transaction, security_activitylog")
        messages.success(request, "Database successfully optimized!")
        return redirect('maintenance:maintenance_dashboard') # Fixed redirect

    # 3. RENDER WITH REPORT AND DB SIZE
    context = {
        'db_size': get_current_db_size(),
        'report': report,
        'last_backup_time': get_last_backup_time(), # <--- IDAGDAG ITO
    }
    return render(request, 'dashboard/settings_hub.html', context)


# BACKUP & RESTORE VIEWS
def trigger_backup(request):
    if request.method == 'POST':
        try:
            call_command('backup_db')
            
            backup_dir = os.path.join(settings.BASE_DIR, 'secure_backups')
            files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir)]
            latest_file = max(files, key=os.path.getctime)
            
            response = FileResponse(open(latest_file, 'rb'), as_attachment=True)
            return response
            
        except Exception as e:
            messages.error(request, f'Backup failed: {e}')
            return redirect('maintenance:maintenance_dashboard') # Fixed redirect

def trigger_restore(request):
    if request.method == 'POST' and request.FILES.get('backup_file'):
        uploaded_file = request.FILES['backup_file']
        fs = FileSystemStorage(location=os.path.join(settings.BASE_DIR, 'secure_backups'))
        
        filename = fs.save(uploaded_file.name, uploaded_file)
        filepath = fs.path(filename)
        
        try:
            call_command('restore_db', filepath)
            messages.success(request, 'System successfully restored!')
        except Exception as e:
            messages.error(request, f'Restore failed: {e}')
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
                
        return redirect('maintenance:maintenance_dashboard') # Fixed redirect

def delete_all_data(request):
    if request.method == 'POST':
        try:
            call_command('flush', '--no-input')
            messages.success(request, 'All database records have been securely deleted.')
        except Exception as e:
            messages.error(request, f'Error deleting data: {e}')
            
    return redirect('maintenance:maintenance_dashboard') # Fixed redirect

def get_last_backup_time():
    backup_dir = os.path.join(settings.BASE_DIR, 'secure_backups')
    
    # Check kung nag-e-exist yung folder
    if not os.path.exists(backup_dir):
        return "No backups yet"
    
    # Kunin lang yung mga backup files (gz o sqlite3)
    files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith('.gz') or f.endswith('.sqlite3')]
    
    # Check kung may laman yung folder
    if not files:
        return "No backups yet"
        
    # Hanapin ang pinaka-latest at i-format ang oras
    latest_file = max(files, key=os.path.getctime)
    dt_object = datetime.fromtimestamp(os.path.getctime(latest_file))
    
    # Output example: May 24, 2026 - 04:30 PM
    return dt_object.strftime("%B %d, %Y - %I:%M %p")