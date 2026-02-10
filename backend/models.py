from sqlalchemy import Column, Integer, String, Enum, DateTime, func, Text, UniqueConstraint, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import enum
import datetime

class ProtocolEnum(str, enum.Enum):
    TCP = "tcp"
    UDP = "udp"

class PortStateEnum(str, enum.Enum):
    ACTIVE = "active"
    DISAPPEARED = "disappeared"

class EventTypeEnum(str, enum.Enum):
    APPEARED = "appeared"
    ALIVE = "alive"
    DISAPPEARED = "disappeared"

class RiskLevelEnum(str, enum.Enum):
    TRUSTED = "trusted"
    EXPECTED = "expected"
    SUSPICIOUS = "suspicious"

class ServiceTypeEnum(str, enum.Enum):
    WEB = "web"
    DB = "db"
    TUNNEL = "tunnel"
    TEST = "test"
    UNKNOWN = "unknown"
    OTHER = "other"

class PortRuntime(Base):
    """
    事实表：机器自动写入
    """
    __tablename__ = "port_runtime"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(String, default="local", index=True)
    protocol = Column(String, index=True) # "tcp" or "udp"
    port = Column(Integer, index=True)

    first_seen_at = Column(DateTime, default=func.now())
    last_seen_at = Column(DateTime, default=func.now())
    last_disappeared_at = Column(DateTime, nullable=True)
    
    current_state = Column(String, default=PortStateEnum.ACTIVE.value) # Use string for SQLite compatibility ease or Enum
    
    current_pid = Column(Integer, nullable=True)
    process_name = Column(String, nullable=True)
    cmdline = Column(String, nullable=True)
    
    total_seen_count = Column(Integer, default=1)
    total_uptime_seconds = Column(Integer, default=0)

    # Relationship to events
    events = relationship("PortEvent", back_populates="runtime", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('host_id', 'protocol', 'port', name='uq_port_runtime_host_proto_port'),
    )

class PortEvent(Base):
    """
    事件表：时间线
    """
    __tablename__ = "port_event"

    id = Column(Integer, primary_key=True, index=True)
    port_runtime_id = Column(Integer, ForeignKey("port_runtime.id"))
    event_type = Column(String) # appeared / alive / disappeared
    timestamp = Column(DateTime, default=func.now())
    pid = Column(Integer, nullable=True)
    process_name = Column(String, nullable=True)

    runtime = relationship("PortRuntime", back_populates="events")

class PortNote(Base):
    """
    语义表：人工维护，记忆
    """
    __tablename__ = "port_note"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(String, default="local", index=True)
    protocol = Column(String, index=True)
    port = Column(Integer, index=True)

    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    owner = Column(String, nullable=True)
    service_type = Column(String, default=ServiceTypeEnum.UNKNOWN.value)
    risk_level = Column(String, default=RiskLevelEnum.EXPECTED.value)
    tags = Column(Text, nullable=True) # Simplified as Text (comma separated or JSON string)

    # Explicitly NO ForeignKey to PortRuntime
    __table_args__ = (
        UniqueConstraint('host_id', 'protocol', 'port', name='uq_port_note_host_proto_port'),
    )
