import subprocess
import logging
import psutil
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
import models
import re

logger = logging.getLogger(__name__)

# 获取主机名 (用于区分多机)
try:
    with open("/etc/hostname", "r") as f:
        HOST_ID = f.read().strip()
except:
    import socket
    HOST_ID = socket.gethostname()

def get_ports_snapshot():
    """
    Linux Only: Uses `ss` command to get listening ports.
    """
    snapshot = []
    
    try:
        # -l: listening
        # -n: numeric
        # -t: tcp
        # -u: udp
        # -p: processes
        # -H: no header
        # Output format example:
        # tcp    LISTEN     0      128    0.0.0.0:22                     0.0.0.0:*                   users:(("sshd",pid=860,fd=3))
        output = subprocess.check_output(["ss", "-lntupH"], text=True)
    except FileNotFoundError:
        logger.error("'ss' command not found. Please install iproute2 package.")
        return []
    except Exception as e:
        logger.error(f"Error executing ss: {e}")
        return []

    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        
        protocol_raw = parts[0] # tcp, udp, u_str, etc.
        state = parts[1]
        
        # Mapping: tcp -> tcp, udp -> udp, tcp6 -> tcp, udp6 -> udp
        if 'tcp' in protocol_raw:
            protocol = 'tcp'
            if state != 'LISTEN': continue
        elif 'udp' in protocol_raw:
            protocol = 'udp'
        else:
            continue
        
        local_addr = parts[4]
        # Extract port. Handling IPv4 0.0.0.0:80 and IPv6 [::]:80
        try:
            if ']:' in local_addr: # IPv6
                    port = int(local_addr.split(']:')[-1])
            else:
                port = int(local_addr.split(':')[-1])
        except ValueError:
            continue
        
        # Parse users/pid
        # Common formats:
        # users:(("sshd",pid=860,fd=3))
        # users:(("nginx",pid=123,fd=4),("nginx",pid=124,fd=4))
        pid = None
        process_name = None
        cmdline = ""
        
        if 'users:' in line:
            try:
                # Regex is safer than split here
                pid_match = re.search(r'pid=(\d+)', line)
                if pid_match:
                    pid = int(pid_match.group(1))
                    
                name_match = re.search(r'"([^"]+)"', line)
                if name_match:
                    process_name = name_match.group(1)
            except Exception:
                pass
        
        # Enhance info with psutil if PID exists (Linux /proc access)
        if pid:
            try:
                proc = psutil.Process(pid)
                # Ensure we don't overwrite if ss gave us a name, but psutil usually better
                process_name = proc.name() 
                cmdline = " ".join(proc.cmdline())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process might have died or we are not root
                pass

        snapshot.append({
            "protocol": protocol,
            "port": port,
            "pid": pid,
            "process_name": process_name,
            "cmdline": cmdline
        })

    return snapshot

def run_collection_cycle():
    logger.info("Starting collection cycle (Frequency: 1h)...")
    db: Session = SessionLocal()
    try:
        current_snapshot = get_ports_snapshot()
        now = datetime.now()
        
        if not current_snapshot:
            logger.warning("Snapshot is empty. Check if 'ss' is returning data/permissions.")
        
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
                
                if runtime.current_state == models.PortStateEnum.DISAPPEARED.value:
                    # RE-APPEARED
                    runtime.current_state = models.PortStateEnum.ACTIVE.value
                    runtime.last_seen_at = now
                    runtime.total_seen_count += 1
                    
                    event = models.PortEvent(
                        port_runtime_id=runtime.id,
                        event_type=models.EventTypeEnum.APPEARED.value,
                        timestamp=now,
                        pid=data['pid'],
                        process_name=data['process_name']
                    )
                    db.add(event)
                else:
                    # Alive
                    # Check for Process Change (Hijack detection / Service Swaps)
                    # We check if process_name changed and is not None
                    if (runtime.process_name and data['process_name'] and 
                        runtime.process_name != data['process_name']):
                        
                        logger.warning(f"Process Changed on port {port}: {runtime.process_name} -> {data['process_name']}")
                        
                        event = models.PortEvent(
                            port_runtime_id=runtime.id,
                            event_type=models.EventTypeEnum.PROCESS_CHANGE.value,
                            timestamp=now,
                            pid=data['pid'],
                            process_name=data['process_name']
                        )
                        db.add(event)
                        
                        # OPTIONAL: Downgrade trust if needed? 
                        # For now, we just record the memory. The UI will show the new process name.
                        
                    runtime.last_seen_at = now
                
                if data['pid']: runtime.current_pid = data['pid']
                if data['process_name']: runtime.process_name = data['process_name']
                if data['cmdline']: runtime.cmdline = data['cmdline']

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
                db.flush() 
                
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
                    # Disappeared
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
