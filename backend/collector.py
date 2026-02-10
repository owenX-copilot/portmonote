import subprocess
import platform
import re
import logging
import psutil
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
import models

logger = logging.getLogger(__name__)

HOST_ID = platform.node()

def get_ports_snapshot():
    """
    Returns a list of dicts:
    [
      {
        "protocol": "tcp",
        "port": 3306,
        "pid": 1234,
        "process_name": "mysqld",
        "cmdline": "/usr/sbin/mysqld"
      }
    ]
    """
    system = platform.system().lower()
    
    snapshot = []

    if system == "linux":
        # User requested 'ss' parser
        try:
            # -l: listening
            # -n: numeric
            # -t: tcp
            # -u: udp
            # -p: processes
            # -H: no header
            output = subprocess.check_output(["ss", "-lntupH"], text=True)
            for line in output.splitlines():
                # Example line: 
                # tcp    LISTEN     0      128    0.0.0.0:22                     0.0.0.0:*                   users:(("sshd",pid=860,fd=3))
                # Need to parse this. 
                # Simplification: Use regex to extract basic info
                parts = line.split()
                if len(parts) < 5:
                    continue
                
                protocol = parts[0] # tcp or udp
                state = parts[1]
                if protocol == 'tcp' and state != 'LISTEN':
                    continue
                
                local_addr = parts[4]
                # Extract port
                if ']:' in local_addr: # IPv6
                     port = int(local_addr.split(']:')[-1])
                else:
                    port = int(local_addr.split(':')[-1])
                
                # Parse users/pid
                # users:(("sshd",pid=860,fd=3))
                pid = None
                process_name = None
                cmdline = ""
                
                if 'users:' in line:
                    try:
                        user_info = line.split('users:((')[1].split('))')[0]
                        # "sshd",pid=860,fd=3
                        first_proc = user_info.split('),(')[0] # Handle multiple users if any
                        # "sshd",pid=860,fd=3
                        
                        proc_parts = first_proc.split(',')
                        p_name = proc_parts[0].strip('"')
                        p_id_str = [p for p in proc_parts if 'pid=' in p]
                        if p_id_str:
                            pid = int(p_id_str[0].split('=')[1])
                            process_name = p_name
                    except Exception:
                        pass
                
                if pid:
                    try:
                        proc = psutil.Process(pid)
                        cmdline = " ".join(proc.cmdline())
                        if not process_name:
                            process_name = proc.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                snapshot.append({
                    "protocol": protocol,
                    "port": port,
                    "pid": pid,
                    "process_name": process_name,
                    "cmdline": cmdline
                })
        except FileNotFoundError:
             logger.error("ss command not found, falling back to psutil")
             return get_ports_snapshot_cross_platform()
        except Exception as e:
            logger.error(f"Error executing ss: {e}")
            return get_ports_snapshot_cross_platform()

    else:
        # Windows/Mac fallback using psutil directly
        return get_ports_snapshot_cross_platform()

    return snapshot

def get_ports_snapshot_cross_platform():
    snapshot = []
    # psutil.net_connections(kind='inet')
    try:
        connections = psutil.net_connections(kind='inet')
        for conn in connections:
            if conn.status == psutil.CONN_LISTEN or conn.type == 2: # TCP LISTEN or UDP (type 2 is SOCK_DGRAM)
                
                protocol = 'tcp' if conn.type == 1 else 'udp' # 1=TCP, 2=UDP
                if protocol == 'tcp' and conn.status != psutil.CONN_LISTEN:
                    continue
                
                pid = conn.pid
                port = conn.laddr.port
                
                process_name = None
                cmdline = ""
                if pid:
                    try:
                        proc = psutil.Process(pid)
                        process_name = proc.name()
                        cmdline = " ".join(proc.cmdline())
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                snapshot.append({
                    "protocol": protocol,
                    "port": port,
                    "pid": pid,
                    "process_name": process_name,
                    "cmdline": cmdline
                })
    except Exception as e:
        logger.error(f"psutil error: {e}")
    return snapshot


def run_collection_cycle():
    logger.info("Starting collection cycle (Frequency: 1h)...")
    db: Session = SessionLocal()
    try:
        current_snapshot = get_ports_snapshot()
        now = datetime.now()
        
        # 1. Build map of current scan: (proto, port) -> data
        scan_map = {}
        for item in current_snapshot:
            key = (item['protocol'], item['port'])
            scan_map[key] = item

        # 2. Get all known runtimes from DB for this host
        known_runtimes = db.query(models.PortRuntime).filter(models.PortRuntime.host_id == HOST_ID).all()
        known_map = {(r.protocol, r.port): r for r in known_runtimes}

        # 3. Process scan results
        for key, data in scan_map.items():
            protocol, port = key
            
            if key in known_map:
                # Exists
                runtime = known_map[key]
                
                # Check if it was disappeared
                if runtime.current_state == models.PortStateEnum.DISAPPEARED.value:
                    # RE-APPEARED
                    runtime.current_state = models.PortStateEnum.ACTIVE.value
                    runtime.last_seen_at = now
                    runtime.total_seen_count += 1
                    # Log Event
                    event = models.PortEvent(
                        port_runtime_id=runtime.id,
                        event_type=models.EventTypeEnum.APPEARED.value,
                        timestamp=now,
                        pid=data['pid'],
                        process_name=data['process_name']
                    )
                    db.add(event)
                else:
                    # Still ALIVE
                    runtime.last_seen_at = now
                    # Optional: Log ALIVE event sparingly? Or implies heartbeat.
                    # User said: "Yellow: Appeared/Disappeared >= N times".
                    # We update simple attributes
                
                # Update details if changed
                if data['pid']:
                    runtime.current_pid = data['pid']
                if data['process_name']:
                    runtime.process_name = data['process_name']
                if data['cmdline']:
                    runtime.cmdline = data['cmdline']

                # Update uptime approx (seconds since last check? rough calc)
                # Simple logic: increment by interval (e.g. 10s) if active
                # For now, we can recalculate uptime based on first_seen if continuous, but that's hard.
                # Let's just create 'total_uptime_seconds' logic later or heuristic.
                
            else:
                # NEW
                runtime = models.PortRuntime(
                    host_id=HOST_ID,
                    protocol=protocol,
                    port=port,
                    first_seen_at=now,
                    last_seen_at=now,
                    current_state=models.PortStateEnum.ACTIVE.value,
                    current_pid=data['pid'],
                    process_name=data['process_name'],
                    cmdline=data['cmdline'],
                    total_seen_count=1
                )
                db.add(runtime)
                db.flush() # get id
                
                event = models.PortEvent(
                    port_runtime_id=runtime.id,
                    event_type=models.EventTypeEnum.APPEARED.value,
                    timestamp=now,
                    pid=data['pid'],
                    process_name=data['process_name']
                )
                db.add(event)

        # 4. Check for disappeared ports
        for key, runtime in known_map.items():
            if key not in scan_map:
                if runtime.current_state == models.PortStateEnum.ACTIVE.value:
                    # Just Disappeared
                    runtime.current_state = models.PortStateEnum.DISAPPEARED.value
                    runtime.last_disappeared_at = now
                    
                    event = models.PortEvent(
                        port_runtime_id=runtime.id,
                        event_type=models.EventTypeEnum.DISAPPEARED.value,
                        timestamp=now,
                        pid=runtime.current_pid,
                        process_name=runtime.process_name
                    )
                    db.add(event)

        db.commit()
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        db.rollback()
    finally:
        db.close()
