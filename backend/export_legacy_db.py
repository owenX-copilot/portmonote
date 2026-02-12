# backend/export_legacy_db.py
import json
import os
import sys
from datetime import datetime, date

# Append current directory to path to import models
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import your existing models
# Assuming models.py and database.py are in the same directory
from models import PortRuntime, PortNote, PortEvent, Base
from database import ENGINE_URL # Or hardcode string if database.py is complex

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))

def export_data():
    # Connect to the legacy database
    # Assuming the script runs from backend/ directory and db is there
    # Update as needed: sqlite:///../backend/portmonote.db or similar
    
    # Try to find the db. 
    db_path = "portmonote.db" 
    if not os.path.exists(db_path):
        # Fallback for some deployments
        db_path = "instance/portmonote.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Could not find database file in current or instance/ folder.")
        print(f"   Please run this script from the directory containing portmonote.db")
        return

    print(f"📂 Opening database: {db_path}")
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    output_file = "../legacy_export.json"

    data = {
        "runtimes": [],
        "notes": [],
        "events": []
    }

    # 1. Export Runtimes
    runtimes = session.query(PortRuntime).all()
    print(f"📦 Found {len(runtimes)} runtimes")
    for r in runtimes:
        data["runtimes"].append({
            "id": r.id,
            "host_id": r.host_id,
            "protocol": r.protocol,
            "port": r.port,
            "first_seen_at": r.first_seen_at,
            "last_seen_at": r.last_seen_at,
            "last_disappeared_at": r.last_disappeared_at,
            "current_state": r.current_state,
            "current_pid": r.current_pid,
            "process_name": r.process_name,
            "cmdline": r.cmdline,
            "total_seen_count": r.total_seen_count,
            "total_uptime_seconds": r.total_uptime_seconds
        })

    # 2. Export Notes
    notes = session.query(PortNote).all()
    print(f"📝 Found {len(notes)} notes")
    for n in notes:
        data["notes"].append({
            "id": n.id,
            "host_id": n.host_id,
            "protocol": n.protocol,
            "port": n.port,
            "title": n.title,
            "description": n.description,
            "owner": n.owner,
            "risk_level": n.risk_level,
            "is_pinned": n.is_pinned
        })

    # 3. Export Events (Limit to recent ones if too big?)
    # For now, export all. 
    events = session.query(PortEvent).all()
    print(f"📅 Found {len(events)} events")
    for e in events:
         data["events"].append({
             "id": e.id,
             "port_runtime_id": e.port_runtime_id,
             "event_type": e.event_type,
             "timestamp": e.timestamp,
             "pid": e.pid,
             "process_name": e.process_name
         })

    # Save to JSON
    with open(output_file, "w", encoding='utf-8') as f:
        json.dump(data, f, default=json_serial, indent=2, ensure_ascii=False)

    print(f"✅ Export complete! File saved to: {os.path.abspath(output_file)}")
    session.close()

if __name__ == "__main__":
    export_data()
