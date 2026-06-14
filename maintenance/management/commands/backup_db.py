import os
import shutil
import subprocess
import datetime
import gzip 
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
            
            raw_sql_path = os.path.join(backup_dir, f"temp_{timestamp}.sql")
            
            db_user = db_settings['USER']
            db_password = db_settings.get('PASSWORD', '')
            db_host = db_settings.get('HOST', 'localhost')


            possible_dump_paths = [
                'mysqldump', 
                r'C:\xampp\mysql\bin\mysqldump.exe',
                r'D:\xampp\mysql\bin\mysqldump.exe',
                r'E:\xampp\mysql\bin\mysqldump.exe',
                r'F:\xampp\mysql\bin\mysqldump.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.1\bin\mysqldump.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe',
                r'"D:\xampp\mysql\bin\mysqldump.exe"',
                r'"D:\xampp\mysql\bin\mysql.exe"',
                r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe',
            ]
            
            mysqldump_exe = None
            for path in possible_dump_paths:
                if path == 'mysqldump' and shutil.which('mysqldump'):
                    mysqldump_exe = 'mysqldump'
                    break
                elif os.path.exists(path):
                    mysqldump_exe = path
                    break
                    
            if not mysqldump_exe:
                raise Exception("Unable to find mysql.exe for the restore process.")

            self.stdout.write(f"Starting MySQL backup for {db_name}...")
            
            dump_cmd = [
                mysqldump_exe,
                f"--user={db_user}",
            ]
            
            if db_host and db_host != 'localhost':
                dump_cmd.append(f"--host={db_host}")
                
            if db_password:
                dump_cmd.append(f"--password={db_password}")
                
            dump_cmd.append(db_name)
            
            try:
                with open(raw_sql_path, 'w', encoding='utf-8') as f_out:
                    process = subprocess.run(
                        dump_cmd, 
                        stdout=f_out, 
                        stderr=subprocess.PIPE, 
                        text=True,
                        check=False
                    )
                
                if process.returncode != 0:
                    error_msg = process.stderr.strip()
                    raise Exception(f"MySQL Error Details: {error_msg}")
                
                with open(raw_sql_path, 'rb') as f_in:
                    with gzip.open(filepath, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        
                os.remove(raw_sql_path)
                self.stdout.write(self.style.SUCCESS(f'SUCCESS: MySQL Backup saved to {filepath}'))
                
            except Exception as e:
                if os.path.exists(raw_sql_path):
                    os.remove(raw_sql_path)
                raise Exception(f'{e}')