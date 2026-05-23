from django.shortcuts import render, redirect
from django.db import connection
from django.contrib import messages

# Dito natin ilalagay ang helper function para hindi na mag-NameError
def get_current_db_size():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT round(sum(data_length + index_length) / 1024 / 1024, 2) 
            FROM information_schema.tables 
            WHERE table_schema = 'jbson_dev';
        """)
        result = cursor.fetchone()
        return result[0] if result and result[0] else 0

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
        return redirect('maintenance:maintenance_dashboard')

    # 3. RENDER WITH REPORT AND DB SIZE
    context = {
        'db_size': get_current_db_size(),
        'report': report,
    }
    return render(request, 'dashboard/settings_hub.html', context)