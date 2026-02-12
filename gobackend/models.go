package main

import (
	"time"
)

type Protocol string

const (
	TCP Protocol = "tcp"
	UDP Protocol = "udp"
)

type PortState string

const (
	StateActive      PortState = "active"
	StateDisappeared PortState = "disappeared"
)

type EventType string

const (
	EventAppeared      EventType = "appeared"
	EventAlive         EventType = "alive"
	EventDisappeared   EventType = "disappeared"
	EventProcessChange EventType = "process_change"
	EventAcknowledged  EventType = "acknowledged"
)

type RiskLevel string

const (
	RiskTrusted    RiskLevel = "trusted"
	RiskExpected   RiskLevel = "expected"
	RiskSuspicious RiskLevel = "suspicious"
)

// PortRuntime: Facts (Machine generated)
type PortRuntime struct {
	ID       uint   `gorm:"primaryKey" json:"id"`
	HostID   string `gorm:"index;default:local" json:"host_id"`
	Protocol string `gorm:"index" json:"protocol"` // "tcp" or "udp"
	Port     int    `gorm:"index" json:"port"`

	FirstSeenAt       time.Time  `json:"first_seen_at"`
	LastSeenAt        time.Time  `json:"last_seen_at"`
	LastDisappearedAt *time.Time `json:"last_disappeared_at"`

	CurrentState string `gorm:"default:active" json:"current_state"` // active, disappeared

	CurrentPID  int    `json:"current_pid"`
	ProcessName string `json:"process_name"`
	Cmdline     string `json:"cmdline"`

	TotalSeenCount     int `gorm:"default:1" json:"total_seen_count"`
	TotalUptimeSeconds int `gorm:"default:0" json:"total_uptime_seconds"`

	Events []PortEvent `gorm:"foreignKey:PortRuntimeID;constraint:OnDelete:CASCADE;" json:"events,omitempty"`
}

// Composite Index equivalent in GORM
func (PortRuntime) TableName() string {
	return "port_runtime"
}

// PortEvent: Timeline
type PortEvent struct {
	ID            uint      `gorm:"primaryKey" json:"id"`
	PortRuntimeID uint      `gorm:"index" json:"port_runtime_id"`
	EventType     string    `json:"event_type"` // appeared, process_change, etc
	Timestamp     time.Time `json:"timestamp"`
	PID           int       `json:"pid"`
	ProcessName   string    `json:"process_name"`
}

func (PortEvent) TableName() string {
	return "port_event"
}

// PortNote: User knowledge
type PortNote struct {
	ID       uint   `gorm:"primaryKey" json:"id"`
	HostID   string `gorm:"index;default:local" json:"host_id"`
	Protocol string `gorm:"index" json:"protocol"`
	Port     int    `gorm:"index" json:"port"`

	Title       string `json:"title"`
	Description string `json:"description"`
	Owner       string `json:"owner"`
	RiskLevel   string `gorm:"default:expected" json:"risk_level"`
	IsPinned    bool   `gorm:"default:false" json:"is_pinned"`
}

func (PortNote) TableName() string {
	return "port_note"
}

// DTO for merged response
type MergedPortItem struct {
	// Key
	HostID   string `json:"host_id"`
	Protocol string `json:"protocol"`
	Port     int    `json:"port"`

	// Runtime
	RuntimeID         uint       `json:"runtime_id"`
	FirstSeenAt       *time.Time `json:"first_seen_at"`
	LastSeenAt        *time.Time `json:"last_seen_at"`
	LastDisappearedAt *time.Time `json:"last_disappeared_at"`
	CurrentState      string     `json:"current_state"`
	CurrentPID        int        `json:"current_pid"`
	ProcessName       string     `json:"process_name"`
	Cmdline           string     `json:"cmdline"`
	UptimeHuman       string     `json:"uptime_human"`

	// Note
	NoteID      uint   `json:"note_id"`
	Title       string `json:"title"`
	Description string `json:"description"`
	Owner       string `json:"owner"`
	RiskLevel   string `json:"risk_level"` // Default "unknown"
	IsPinned    bool   `json:"is_pinned"`

	// Derived
	DerivedStatus        string     `json:"derived_status"`    // healthy, flapping, suspicious, ghost
	LatestEventType      string     `json:"latest_event_type"` // For UI warning
	LatestEventTimestamp *time.Time `json:"latest_event_timestamp"`
}

// Note Update Request
type NoteUpdateRequest struct {
	Title       *string `json:"title"`
	Description *string `json:"description"`
	Owner       *string `json:"owner"`
	RiskLevel   *string `json:"risk_level"`
	IsPinned    *bool   `json:"is_pinned"`
}
