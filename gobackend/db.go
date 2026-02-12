package main

import (
	"log"
	"os"
	"path/filepath"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var DB *gorm.DB

func InitDB(ignoredDSN string) {
	// Strict Path Logic:
	// Always look in ./data/portmonote.db for the database.
	// We create the directory if it doesn't exist.

	const dbDir = "data"
	const dbFile = "portmonote.db"
	finalDSN := filepath.Join(dbDir, dbFile)

	// Ensure directory exists
	if _, err := os.Stat(dbDir); os.IsNotExist(err) {
		log.Printf("📂 Creating data directory: %s", dbDir)
		if err := os.Mkdir(dbDir, 0755); err != nil {
			log.Fatalf("❌ Failed to create data directory: %v", err)
		}
	}

	// Check file existence for logging purposes only
	if _, err := os.Stat(finalDSN); os.IsNotExist(err) {
		log.Printf("⚠️ Database file '%s' NOT FOUND. A new database will be created.", finalDSN)
	} else {
		log.Printf("✅ Found database file: %s", finalDSN)
	}

	var err error
	DB, err = gorm.Open(sqlite.Open(finalDSN), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Error),
	})
	if err != nil {
		log.Fatal("Failed to connect to database:", err)
	}

	// Auto Migrate
	err = DB.AutoMigrate(&PortRuntime{}, &PortEvent{}, &PortNote{})
	if err != nil {
		log.Fatal("Failed to migrate database:", err)
	}
}
