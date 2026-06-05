# user_manual/views.py
from django.shortcuts import render

def manual_hub(request):
    return render(request, 'user_manual/manual_hub.html', {'active_tab': 'none'})

def dashboard_guide(request):
    return render(request, 'user_manual/dashboard_guide.html', {'active_tab': 'dashboard'})

def general_manual(request):
    return render(request, 'user_manual/general_guide.html', {'active_tab': 'general'})

def inventory_manual(request):
    return render(request, 'user_manual/inventory_guide.html', {'active_tab': 'inventory'})

def pos_manual(request):
    return render(request, 'user_manual/pos_guide.html', {'active_tab': 'pos'})

def billing_manual(request):
    return render(request, 'user_manual/billing_guide.html', {'active_tab': 'billing'})

def reports_guide(request):
    return render(request, 'user_manual/reports_guide.html', {'active_tab': 'reports'})

def management_guide(request):
    return render(request, 'user_manual/management_guide.html', {'active_tab': 'management'})

def settings_guide(request):
    return render(request, 'user_manual/settings_guide.html', {'active_tab': 'settings'})
