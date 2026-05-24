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

        # Extract gz to a temporary SQL file first (Windows friendly)
        temp_sql_path = os.path.join(settings.BASE_DIR, 'secure_backups', 'temp_restore.sql')
        
        try:
            self.stdout.write("Extracting backup file...")
            with gzip.open(filepath, 'rb') as f_in:
                with open(temp_sql_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            self.stdout.write("Restoring to MySQL database...")
            
            # Windows command to pipe the SQL file into mysql
            restore_cmd = f"mysql -h {db_host} -u {db_user} -p{db_password} {db_name} < \"{temp_sql_path}\""
            subprocess.run(restore_cmd, shell=True, check=True)
            
            self.stdout.write(self.style.SUCCESS('SUCCESS: Database successfully restored from backup!'))
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f'Recovery failed during MySQL import: {e}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Recovery failed: {e}'))
        finally:
            # Clean up the temporary extracted file
            if os.path.exists(temp_sql_path):
                os.remove(temp_sql_path)