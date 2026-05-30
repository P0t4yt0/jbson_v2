# user_manual/views.py
from django.shortcuts import render

def manual_hub(request):
    # Ito yung default page kapag clinick ang User Manual sa sidebar
    return render(request, 'user_manual/manual_hub.html', {'active_tab': 'none'})

def dashboard_guide(request):
    # Ipapasa natin yung 'dashboard' as active_tab para mag-highlight yung button
    return render(request, 'user_manual/dashboard_guide.html', {'active_tab': 'dashboard'})

def general_manual(request):
    return render(request, 'user_manual/general_guide.html', {'active_tab': 'general'})

def inventory_manual(request):
    return render(request, 'user_manual/inventory_guide.html', {'active_tab': 'inventory'})

def pos_manual(request):
    return render(request, 'user_manual/pos_guide.html', {'active_tab': 'pos'})

def billing_manual(request):
    return render(request, 'user_manual/billing_guide.html', {'active_tab': 'billing'})