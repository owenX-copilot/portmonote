package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// CustomTime unmarshaling to handle formats without timezone
type CustomTime struct {
	time.Time
}

func (ct *CustomTime) UnmarshalJSON(b []byte) error {
	s := string(b)
	if s == "null" {
		ct.Time = time.Time{}
		return nil
	}
	// Try parsing standard RFC3339 first
	t, err := time.Parse(`"`+time.RFC3339+`"`, s)
	if err == nil {
		ct.Time = t
		return nil
	}
	// Try parsing format from python isoformat() without TZ (e.g. "2026-02-10T11:55:10.009789")
	t, err = time.Parse(`"2006-01-02T15:04:05.999999"`, s)
	if err == nil {
		ct.Time = t
		return nil
	}
	// Try parsing format without microsecond
	t, err = time.Parse(`"2006-01-02T15:04:05"`, s)
	if err == nil {
		ct.Time = t
		return nil
	}

	return err
}

// Define structures matching JSON export
type ExportData struct {
	Runtimes []struct {
		ID                 uint        `json:"id"`
		HostID             string      `json:"host_id"`
		Protocol           string      `json:"protocol"`
		Port               int         `json:"port"`
		FirstSeenAt        CustomTime  `json:"first_seen_at"`
		LastSeenAt         CustomTime  `json:"last_seen_at"`
		LastDisappearedAt  *CustomTime `json:"last_disappeared_at"`
		CurrentState       string      `json:"current_state"`
		CurrentPID         int         `json:"current_pid"`
		ProcessName        string      `json:"process_name"`
		Cmdline            string      `json:"cmdline"`
		TotalSeenCount     int         `json:"total_seen_count"`
		TotalUptimeSeconds int         `json:"total_uptime_seconds"`
	} `json:"runtimes"`

	Notes []PortNote `json:"notes"`

	Events []struct {
		ID            uint       `json:"id"`
		PortRuntimeID uint       `json:"port_runtime_id"`
		EventType     string     `json:"event_type"`
		Timestamp     CustomTime `json:"timestamp"`
		PID           int        `json:"pid"`
		ProcessName   string     `json:"process_name"`
	} `json:"events"`
}

func main() {
	jsonPath := flag.String("import", "", "Path to legacy_export.json file")
	dbPath := flag.String("db", "data/portmonote.db", "Path to SQLite database to write to")
	flag.Parse()

	if *jsonPath == "" {
		fmt.Println("Usage: go run import_legacy.go -import ../legacy_export.json")
		os.Exit(1)
	}

	// 1. Read JSON file
	file, err := os.Open(*jsonPath)
	if err != nil {
		log.Fatalf("❌ Failed to open JSON file: %v", err)
	}
	defer file.Close()

	byteValue, _ := io.ReadAll(file)
	var data ExportData
	if err := json.Unmarshal(byteValue, &data); err != nil {
		log.Fatalf("❌ Failed to parse JSON: %v", err)
	}

	log.Printf("📦 Loaded %d runtimes, %d notes, %d events from JSON",
		len(data.Runtimes), len(data.Notes), len(data.Events))

	// 2. Connect to Output DB
	// Ensure directory exists
	// (omitted detailed mkdir logic, assuming data folder exists or is handled by user)

	db, err := gorm.Open(sqlite.Open(*dbPath), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Info),
	})
	if err != nil {
		log.Fatalf("❌ Failed to connect to DB: %v", err)
	}

	// 3. Migrate Schema (Ensure tables exist)
	log.Println("🔄 Migrating schema...")
	if err := db.AutoMigrate(&PortRuntime{}, &PortNote{}, &PortEvent{}); err != nil {
		log.Fatalf("❌ Migration failed: %v", err)
	}

	// 4. Import Data
	log.Println("🚀 Importing data...")

	// Transaction to ensure integrity
	err = db.Transaction(func(tx *gorm.DB) error {
		// Clear existing data? Uncomment if needed
		// tx.Exec("DELETE FROM port_runtime")
		// tx.Exec("DELETE FROM port_note")
		// tx.Exec("DELETE FROM port_event")

		if len(data.Runtimes) > 0 {
			// Convert CustomTime structs back to models.PortRuntime
			var runtimes []PortRuntime
			for _, r := range data.Runtimes {
				var lastDisappearedAt *time.Time
				if r.LastDisappearedAt != nil && !r.LastDisappearedAt.IsZero() {
					t := r.LastDisappearedAt.Time
					lastDisappearedAt = &t
				}

				runtimes = append(runtimes, PortRuntime{
					ID:                 r.ID,
					HostID:             r.HostID,
					Protocol:           r.Protocol,
					Port:               r.Port,
					FirstSeenAt:        r.FirstSeenAt.Time,
					LastSeenAt:         r.LastSeenAt.Time,
					LastDisappearedAt:  lastDisappearedAt,
					CurrentState:       r.CurrentState,
					CurrentPID:         r.CurrentPID,
					ProcessName:        r.ProcessName,
					Cmdline:            r.Cmdline,
					TotalSeenCount:     r.TotalSeenCount,
					TotalUptimeSeconds: r.TotalUptimeSeconds,
				})
			}

			if err := tx.CreateInBatches(runtimes, 100).Error; err != nil {
				return err
			}
			log.Println("✅ Imported Runtimes")
		}

		if len(data.Notes) > 0 {
			if err := tx.CreateInBatches(data.Notes, 100).Error; err != nil {
				return err
			}
			log.Println("✅ Imported Notes")
		}

		if len(data.Events) > 0 {
			// Convert CustomTime structs back to models.PortEvent
			var events []PortEvent
			for _, e := range data.Events {
				events = append(events, PortEvent{
					ID:            e.ID,
					PortRuntimeID: e.PortRuntimeID,
					EventType:     e.EventType,
					Timestamp:     e.Timestamp.Time,
					PID:           e.PID,
					ProcessName:   e.ProcessName,
				})
			}

			if err := tx.CreateInBatches(events, 100).Error; err != nil {
				return err
			}
			log.Println("✅ Imported Events")
		}

		return nil
	})

	if err != nil {
		log.Fatalf("❌ Import failed: %v", err)
	}

	log.Println("✨ Import SUCCESS!")
}
