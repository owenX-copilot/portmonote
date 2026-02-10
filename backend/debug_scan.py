import sys
import psutil
import platform
import os

# 临时将当前目录加入 path 以导入 collector
sys.path.append(os.getcwd())

print(f"OS: {platform.system()}")
print(f"Python: {sys.version}")

print("\n--- 1. Testing psutil.net_connections(kind='inet') ---")
try:
    conns = psutil.net_connections(kind='inet')
    print(f"Total connections found: {len(conns)}")
    
    listening = [c for c in conns if c.status == 'LISTEN' or c.type == 2] # 2=UDP
    print(f"Listening/UDP connections: {len(listening)}")
    
    if len(listening) > 0:
        print("First 3 items:")
        for c in listening[:3]:
            print(f"  {c}")
    else:
        print("WARN: No listening ports found. Permissions issue?")
        
except Exception as e:
    print(f"ERROR calling psutil: {e}")

print("\n--- 2. Testing collector.get_ports_snapshot() ---")
try:
    import collector
    snapshot = collector.get_ports_snapshot()
    print(f"Snapshot items: {len(snapshot)}")
    if len(snapshot) > 0:
        print(f"First 3 snapshot items: {snapshot[:3]}")
    else:
        print("WARN: Snapshot is empty.")
except ImportError:
    print("ERROR: Could not import collector. Make sure you run this from 'backend' folder.")
except Exception as e:
    print(f"ERROR calling collector: {e}")
