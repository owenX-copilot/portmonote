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

# Scheduler (Cron mode: Top of every hour)
scheduler = BackgroundScheduler()
# 立即执行一次 (for instant feedback on startup)
scheduler.add_job(collector.run_collection_cycle, 'date', run_date=datetime.now() + timedelta(seconds=1))
# 整点执行 (minute='0', hour='*')
scheduler.add_job(collector.run_collection_cycle, 'cron', minute='0', hour='*')
scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/")
def read_root():
    return FileResponse(os.path.join(FRONTEND_PATH, "index.html"))

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(os.path.join(os.path.dirname(__file__), "favicon.ico"))

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

import subprocess

@app.get("/inspect/{port}")
def inspect_port(port: int):
    """
    Runs `witr --port <port>` and returns the raw output.
    Note: 'witr' must be in the PATH.
    """
    try:
        # Check if witr exists
        subprocess.check_output(["which", "witr"])
    except subprocess.CalledProcessError:
        return {"output": "Error: 'witr' command not found on server.\nPlease install it: https://github.com/pranshuparmar/witr", "error": True}

    try:
        # Run witr with a timeout to prevent hanging
        # witr usually runs continuously? We might need a flag to run once or timeout.
        # Looking at witr docs, it seems to show info and exit? 
        # Actually many top/stat tools wait. 
        # If witr is interactive/watch mode, this will hang.
        # Assuming witr outputs once. If it's a TUI (Text UI), capturing stdout fails.
        # Let's hope it dumps info. If it's a monitor, we might just grab first 2s.
        
        # NOTE: witr is likely a TUI/monitor. We try to run it with a timeout.
        # If it doesn't support 'one-shot' mode, we kill it after 2s and capture output.
        cmd = ["witr", "--port", str(port)]
        
        # Using timeout to capture initial output for tools that update continuously
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            output = result.stdout
        except subprocess.TimeoutExpired as e:
            output = e.stdout or e.stderr or "witr command timed out (it might be interactive)."
            if not output: output = "Collecting data..." # simple fallback

        # Clean up ANSI codes if necessary (TUI often has them)
        # For now, let frontend handle or display raw.
        return {"output": output, "error": False}
        
    except Exception as e:
        return {"output": f"Execution failed: {str(e)}", "error": True}

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
        
        # Get latest event for UI warning
        latest_evt_type = None
        latest_evt_ts = None
        if r and r.events:
            # Sort events desc by id/ts locally since lazy loaded
            # ideally fetched with query, but list is small per port
            sorted_evts = sorted(r.events, key=lambda e: e.id, reverse=True)
            if sorted_evts:
                 latest_evt_type = sorted_evts[0].event_type
                 latest_evt_ts = sorted_evts[0].timestamp

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
            is_pinned=bool(n.is_pinned) if n else False,
            tags=n.tags if n else None,
            
            derived_status=status,
            uptime_human=format_uptime(r.first_seen_at) if r and r.current_state == 'active' else "",
            
            latest_event_type=latest_evt_type,
            latest_event_timestamp=latest_evt_ts
        )
        result.append(item)
        
    return result

@app.get("/history", response_model=List[schemas.PortEventDTO])
def get_port_history(host_id:str, protocol:str, port:int, db: Session = Depends(get_db)):
    runtime = db.query(models.PortRuntime).filter(
        models.PortRuntime.host_id == host_id,
        models.PortRuntime.protocol == protocol,
        models.PortRuntime.port == port
    ).first()
    
    if not runtime:
        return []
        
    events = db.query(models.PortEvent).filter(
        models.PortEvent.port_runtime_id == runtime.id
    ).order_by(models.PortEvent.timestamp.desc()).all()
    
    return events

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

@app.delete("/ports")
def delete_port(host_id: str, protocol: str, port: int, db: Session = Depends(get_db)):
    """
    Hard delete a port (Runtime + Note + Events).
    If the port is currently active, it may reappear on the next scan.
    """
    # 1. Delete Runtime (Cascades Events)
    runtime = db.query(models.PortRuntime).filter(
        models.PortRuntime.host_id == host_id,
        models.PortRuntime.protocol == protocol,
        models.PortRuntime.port == port
    ).first()
    
    if runtime:
        db.delete(runtime)
        
    # 2. Delete Note
    note = db.query(models.PortNote).filter(
        models.PortNote.host_id == host_id,
        models.PortNote.protocol == protocol,
        models.PortNote.port == port
    ).first()
    
    if note:
        db.delete(note)
        
    db.commit()
    return {"status": "deleted"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=2008, reload=True)
