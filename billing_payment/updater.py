# jbson_v2/billing_payment/updater.py

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.management import call_command

def check_invoices_job():
    try:
        # Ito yung mismong command na tina-type mo sa terminal kanina
        call_command('check_invoice')
    except Exception as e:
        print(f"Scheduler Error: {e}")

def start():
    scheduler = BackgroundScheduler()
    
    # ---------------------------------------------------------
    # PARA SA LIVE SYSTEM: Tatakbo araw-araw tuwing 12:00 AM
    scheduler.add_job(check_invoices_job, 'cron', hour=0, minute=0)
    # ---------------------------------------------------------
    
    # KUNG GUSTO MONG I-TEST NGAYON: I-comment out (lagyan ng #) ang linya sa itaas 
    # at tanggalin ang # sa linya sa ibaba para tumakbo siya kada 1 minuto:
    # scheduler.add_job(check_invoices_job, 'interval', minutes=1)

    scheduler.start()