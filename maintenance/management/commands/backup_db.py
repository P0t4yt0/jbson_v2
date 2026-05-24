import os
import shutil
import subprocess
import datetime
import gzip  # Added Python's native gzip
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Automatically generates a backup of the database'

    def handle(self, *args, **kwargs):
        db_settings = settings.DATABASES['default']
        db_engine = db_settings['ENGINE']
        db_name = db_settings['NAME']
        
        backup_dir = os.path.join(settings.BASE_DIR, 'secure_backups')
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

        # --- SQLITE3 BACKUP LOGIC ---
        if 'sqlite3' in db_engine:
            filename = f"db_backup_{timestamp}.sqlite3"
            filepath = os.path.join(backup_dir, filename)
            
            self.stdout.write(f"Starting SQLite backup...")
            try:
                shutil.copy2(db_name, filepath)
                self.stdout.write(self.style.SUCCESS(f'SUCCESS: Backup saved to {filepath}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'WARNING: Backup failed - {e}'))

        # --- MYSQL BACKUP LOGIC ---
        elif 'mysql' in db_engine:
            filename = f"{db_name}_backup_{timestamp}.sql.gz"
            filepath = os.path.join(backup_dir, filename)
            
            # Create a temporary raw SQL file
            raw_sql_path = os.path.join(backup_dir, f"temp_{timestamp}.sql")
            
            db_user = db_settings['USER']
            db_password = db_settings['PASSWORD']
            db_host = db_settings.get('HOST', 'localhost')

            self.stdout.write(f"Starting MySQL backup for {db_name}...")
            
            # Removed the piped gzip to avoid Windows errors
            dump_cmd = f"mysqldump -h {db_host} -u {db_user} -p{db_password} {db_name} > {raw_sql_path}"
            
            try:
                # 1. Run mysqldump to generate raw SQL
                subprocess.run(dump_cmd, shell=True, check=True)
                
                # 2. Compress the SQL file using Python's gzip
                with open(raw_sql_path, 'rb') as f_in:
                    with gzip.open(filepath, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        
                # 3. Clean up the temporary raw SQL file
                os.remove(raw_sql_path)
                
                self.stdout.write(self.style.SUCCESS(f'SUCCESS: MySQL Backup saved to {filepath}'))
            except subprocess.CalledProcessError as e:
                self.stdout.write(self.style.ERROR(f'WARNING: Backup failed - {e}'))
                self.stdout.write(self.style.WARNING("Tip: Make sure MySQL 'bin' folder is in your Windows System PATH."))
        
        else:
            self.stdout.write(self.style.ERROR('Unsupported database engine for automatic backup.'))