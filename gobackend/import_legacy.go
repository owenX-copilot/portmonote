package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// Define structures matching JSON export
type ExportData struct {
	Runtimes []PortRuntime `json:"runtimes"`
	Notes    []PortNote    `json:"notes"`
	Events   []PortEvent   `json:"events"`
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
			if err := tx.CreateInBatches(data.Runtimes, 100).Error; err != nil {
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
			if err := tx.CreateInBatches(data.Events, 100).Error; err != nil {
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
