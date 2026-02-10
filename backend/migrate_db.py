import sqlite3
import os

# Try to locate the db
db_paths = ["portmonote.db", "backend/portmonote.db", "../portmonote.db"]
db_path = None
for p in db_paths:
    if os.path.exists(p):
        db_path = p
        break

if not db_path:
    print("No database file found to migrate. It will be created with new schema on first run.")
else:
    print(f"Migrating database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE port_note ADD COLUMN is_pinned INTEGER DEFAULT 0")
        conn.commit()
        print("Successfully added is_pinned column.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("Column is_pinned already exists.")
        else:
            print(f"Error: {e}")
            
    conn.close()
