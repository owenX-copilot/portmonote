from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from apscheduler.schedulers.background import BackgroundScheduler
import uvicorn
import logging
import os
from datetime import datetime, timedelta

from database import engine, get_db, Base
import models
import schemas
import collector

# Init Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Portmonote API")

# Mount frontend
FRONTEND_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# Scheduler (Scan every 1 hour as requested)
scheduler = BackgroundScheduler()
scheduler.add_job(collector.run_collection_cycle, 'interval', seconds=3600)
scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/")
def read_root():
    return FileResponse(os.path.join(FRONTEND_PATH, "index.html"))

@app.post("/trigger-scan")
def trigger_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(collector.run_collection_cycle)
    return {"message": "Scan triggered in background"}

def calculate_status(runtime: models.PortRuntime, note: models.PortNote) -> schemas.DerivedStatusEnum:
    # Logic from specs
    # 🟢 Healthy: Active + High Uptime (TODO) + Trusted Note
    # 🟡 Flapping: (Simplified - if recently disappeared and reappeared - check count?) 
    #              For now, if State=Active but total_seen_count is high relative time? Hard to simpler.
    #              Let's stick to simple rules first.
    # 🔴 Suspicious: Active + No Note + Process Unknown
    # ⚫ Ghost: Disappeared + Note marked as Expected
    
    is_active = runtime and runtime.current_state == models.PortStateEnum.ACTIVE.value
    is_disappeared = runtime and runtime.current_state == models.PortStateEnum.DISAPPEARED.value
    has_note = note is not None
    is_trusted = has_note and note.risk_level == models.RiskLevelEnum.TRUSTED.value
    is_expected = has_note and note.risk_level == models.RiskLevelEnum.EXPECTED.value
    
    if is_active:
        if is_trusted:
            return schemas.DerivedStatusEnum.HEALTHY
        if not has_note:
            return schemas.DerivedStatusEnum.SUSPICIOUS
        # If active and note exists but not trusted?
        if note.risk_level == models.RiskLevelEnum.SUSPICIOUS.value:
            return schemas.DerivedStatusEnum.SUSPICIOUS
            
        return schemas.DerivedStatusEnum.HEALTHY # Default healthy if active and expected
        
    if is_disappeared:
        if is_expected:
            return schemas.DerivedStatusEnum.GHOST
            
    return schemas.DerivedStatusEnum.UNKNOWN

def format_uptime(dt: datetime) -> str:
    if not dt: return ""
    delta = datetime.now() - dt
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h"

@app.get("/ports", response_model=List[schemas.MergedPortItem])
def get_dashboard_data(db: Session = Depends(get_db)):
    runtimes = db.query(models.PortRuntime).all()
    notes = db.query(models.PortNote).all()
    
    # Key: (host, proto, port)
    merged_map: Dict[tuple, Dict[str, Any]] = {}
    
    # Process Runtimes
    for r in runtimes:
        key = (r.host_id, r.protocol, r.port)
        if key not in merged_map:
            merged_map[key] = {
                "host_id": r.host_id, "protocol": r.protocol, "port": r.port,
                "runtime": r, "note": None
            }
        else:
            merged_map[key]["runtime"] = r
            
    # Process Notes
    for n in notes:
        key = (n.host_id, n.protocol, n.port)
        if key not in merged_map:
            merged_map[key] = {
                "host_id": n.host_id, "protocol": n.protocol, "port": n.port,
                "runtime": None, "note": n
            }
        else:
            merged_map[key]["note"] = n
            
    # Compile Result
    result = []
    for key, val in merged_map.items():
        r = val["runtime"]
        n = val["note"]
        
        # Calculate status
        status = calculate_status(r, n)
        
        item = schemas.MergedPortItem(
            host_id=key[0],
            protocol=key[1],
            port=key[2],
            
            runtime_id=r.id if r else None,
            first_seen_at=r.first_seen_at if r else None,
            last_seen_at=r.last_seen_at if r else None,
            last_disappeared_at=r.last_disappeared_at if r else None,
            current_state=r.current_state if r else "unknown",
            current_pid=r.current_pid if r else None,
            process_name=r.process_name if r else None,
            cmdline=r.cmdline if r else None,
            
            note_id=n.id if n else None,
            title=n.title if n else None,
            description=n.description if n else None,
            owner=n.owner if n else None,
            risk_level=n.risk_level if n else "unknown",
            tags=n.tags if n else None,
            
            derived_status=status,
            uptime_human=format_uptime(r.first_seen_at) if r and r.current_state == 'active' else ""
        )
        result.append(item)
        
    return result

@app.post("/notes", response_model=schemas.PortNoteBase)
def update_note(note_in: schemas.PortNoteCreate, host_id:str, protocol:str, port:int, db: Session = Depends(get_db)):
    # Find existing or create
    note = db.query(models.PortNote).filter(
        models.PortNote.host_id == host_id,
        models.PortNote.protocol == protocol,
        models.PortNote.port == port
    ).first()
    
    if not note:
        note = models.PortNote(
            host_id=host_id,
            protocol=protocol,
            port=port,
            **note_in.dict()
        )
        db.add(note)
    else:
        for k, v in note_in.dict(exclude_unset=True).items():
            setattr(note, k, v)
            
    db.commit()
    db.refresh(note)
    return note

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=2008, reload=True)
