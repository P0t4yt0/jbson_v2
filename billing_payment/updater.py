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
    lock_file = open("scheduler.lock", "w")
    
    try:
        if os.name == 'nt':  
            # Para sa Windows
            import msvcrt
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return  
        else:  
            # Para sa Linux / Mac
            import fcntl
            try:
                fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return  
    except Exception as e:
        print(f"Locking error: {e}")
        return
        
    scheduler = BackgroundScheduler()
    
    scheduler.add_job(check_invoices_job, 'cron', hour=0, minute=0)
    
    # scheduler.add_job(check_invoices_job, 'interval', minutes=1)

    scheduler.start()
    
    atexit.register(lambda: scheduler.shutdown(wait=False))