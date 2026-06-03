# jbson_v2/billing_payment/updater.py

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.management import call_command
import atexit
import os

def check_invoices_job():
    try:
        call_command('check_invoices')
    except Exception as e:
        print(f"Scheduler Error: {e}")

def start():
    # Buksan ang lock file
    lock_file = open("scheduler.lock", "w")
    
    # CROSS-PLATFORM LOCKING
    try:
        if os.name == 'nt':  
            # Para sa Windows
            import msvcrt
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return  # Naka-lock na (may tumatakbo na), wag nang mag-start ng panibago
        else:  
            # Para sa Linux / Mac
            import fcntl
            try:
                fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return  # Naka-lock na
    except Exception as e:
        print(f"Locking error: {e}")
        return
        
    scheduler = BackgroundScheduler()
    
    # ---------------------------------------------------------
    # PARA SA LIVE SYSTEM: Tatakbo araw-araw tuwing 12:00 AM
    scheduler.add_job(check_invoices_job, 'cron', hour=0, minute=0)
    # ---------------------------------------------------------
    
    # KUNG GUSTO MONG I-TEST NGAYON: (Tanggalin ang comment sa ibaba at i-comment ang nasa itaas)
    # scheduler.add_job(check_invoices_job, 'interval', minutes=1)

    scheduler.start()
    
    # Siguraduhing mamamatay ang scheduler kapag isinara ang server
    atexit.register(lambda: scheduler.shutdown(wait=False))