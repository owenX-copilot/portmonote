from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum

class ProtocolEnum(str, Enum):
    TCP = "tcp"
    UDP = "udp"

class PortStateEnum(str, Enum):
    ACTIVE = "active"
    DISAPPEARED = "disappeared"

class RiskLevelEnum(str, Enum):
    TRUSTED = "trusted"
    EXPECTED = "expected"
    SUSPICIOUS = "suspicious"

class DerivedStatusEnum(str, Enum):
    HEALTHY = "healthy"
    FLAPPING = "flapping"
    SUSPICIOUS = "suspicious"
    GHOST = "ghost"
    UNKNOWN = "unknown"

class PortNoteBase(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    service_type: Optional[str] = "unknown"
    risk_level: Optional[str] = "expected"
    is_pinned: Optional[bool] = False
    tags: Optional[str] = None

class PortNoteCreate(PortNoteBase):
    pass

class PortNoteUpdate(PortNoteBase):
    pass

class PortRuntimeDTO(BaseModel):
    id: int
    host_id: str
    protocol: str
    port: int
    first_seen_at: datetime
    last_seen_at: datetime
    last_disappeared_at: Optional[datetime] = None
    current_state: str
    current_pid: Optional[int]
    process_name: Optional[str]
    cmdline: Optional[str]
    total_seen_count: int
    
    class Config:
        orm_mode = True

class MergedPortItem(BaseModel):
    """
    Combined view for the UI Card
    """
    # Keys
    host_id: str
    protocol: str
    port: int
    
    # Runtime Info
    runtime_id: Optional[int]
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    last_disappeared_at: Optional[datetime]
    current_state: str # active / disappeared
    current_pid: Optional[int]
    process_name: Optional[str]
    cmdline: Optional[str]
    
    # Semantic Info
    note_id: Optional[int]
    title: Optional[str]
    description: Optional[str]
    owner: Optional[str]
    risk_level: str
    is_pinned: bool = False
    tags: Optional[str]
    
    # Derived
    derived_status: DerivedStatusEnum
    uptime_human: Optional[str] # "12d 3h"
    
    # Audit
    latest_event_type: Optional[str]
    latest_event_timestamp: Optional[datetime]

class PortEventDTO(BaseModel):
    id: int
    port_runtime_id: int
    event_type: str
    timestamp: datetime
    pid: Optional[int]
    process_name: Optional[str]
    
    class Config:
        orm_mode = True

