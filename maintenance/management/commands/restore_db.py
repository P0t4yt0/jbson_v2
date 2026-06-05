import os
import subprocess
import gzip
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Restores the database from a compressed SQL dump file'

    def add_arguments(self, parser):
        parser.add_argument('filepath', type=str, help='Absolute path to the .sql.gz backup file')

    def handle(self, *args, **kwargs):
        filepath = kwargs['filepath']
        
        if not os.path.exists(filepath):
            self.stdout.write(self.style.ERROR(f'Error: File {filepath} does not exist.'))
            return

        db_settings = settings.DATABASES['default']
        db_name = db_settings['NAME']
        db_user = db_settings['USER']
        db_password = db_settings['PASSWORD']
        db_host = db_settings.get('HOST', 'localhost')

        self.stdout.write(self.style.WARNING(f"WARNING: This will OVERWRITE current data in {db_name}."))
        self.stdout.write(f"Preparing to restore system state from: {filepath}...")

        temp_sql_path = os.path.join(settings.BASE_DIR, 'secure_backups', 'temp_restore.sql')
        
        try:
            self.stdout.write("Extracting backup file...")
            with gzip.open(filepath, 'rb') as f_in:
                with open(temp_sql_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            self.stdout.write("Restoring to MySQL database...")
            
            possible_mysql_paths = [
                'mysql',
                r'C:\xampp\mysql\bin\mysql.exe',
                r'D:\xampp\mysql\bin\mysql.exe',
                r'E:\xampp\mysql\bin\mysql.exe',
                r'F:\xampp\mysql\bin\mysql.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.1\bin\mysql.exe',
                r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe',
            ]
            
            mysql_exe = None
            for path in possible_mysql_paths:
                if path == 'mysql' and shutil.which('mysql'):
                    mysql_exe = 'mysql'
                    break
                elif os.path.exists(path):
                    mysql_exe = path
                    break
                    
            if not mysql_exe:
                raise Exception("Unable to find mysql.exe for the restore process.")

            restore_cmd = [
                mysql_exe,
                f"--user={db_user}",
            ]
            
            if db_host and db_host != 'localhost':
                restore_cmd.append(f"--host={db_host}")
                
            if db_password:
                restore_cmd.append(f"--password={db_password}")
                
            restore_cmd.append(db_name)
            
            with open(temp_sql_path, 'rb') as f_in:
                process = subprocess.run(
                    restore_cmd,
                    stdin=f_in,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False
                )
            
            if process.returncode != 0:
                error_msg = process.stderr.decode('utf-8', errors='ignore').strip()
                raise Exception(f"MySQL Restore Error: {error_msg}")
            
            self.stdout.write(self.style.SUCCESS('SUCCESS: Database successfully restored from backup!'))
            
        except Exception as e:
            raise Exception(f'Recovery failed: {e}')
        finally:
            if os.path.exists(temp_sql_path):
                os.remove(temp_sql_path)