import os
import shutil

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

ensure_dir('catlabel/api')
ensure_dir('catlabel/core')
ensure_dir('catlabel/services')

# Move models and diagnostics to core
if os.path.exists('catlabel/app/models.py'):
    shutil.move('catlabel/app/models.py', 'catlabel/core/models.py')
if os.path.exists('catlabel/app/diagnostics.py'):
    shutil.move('catlabel/app/diagnostics.py', 'catlabel/core/diagnostics.py')

# Move services
for f in ['ai_tools.py', 'layout_engine.py', 'label_templates.py', 'prompts.py']:
    if os.path.exists(f'catlabel/app/{f}'):
        shutil.move(f'catlabel/app/{f}', f'catlabel/services/{f}')

# Move routes_ai
if os.path.exists('catlabel/app/ai_agent.py'):
    shutil.move('catlabel/app/ai_agent.py', 'catlabel/api/routes_ai.py')

# Create database.py
with open('catlabel/core/database.py', 'w') as f:
    f.write('''from sqlmodel import SQLModel, create_engine
import os

os.makedirs("data", exist_ok=True)
sqlite_file_name = "data/catlabel.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
''')

# Clean up unused Phomemo/Niimbot leftover
if os.path.exists('catlabel/app/vendors'):
    shutil.rmtree('catlabel/app/vendors', ignore_errors=True)
if os.path.exists('catlabel/vendors/phomemo/raster.py'):
    os.remove('catlabel/vendors/phomemo/raster.py')
