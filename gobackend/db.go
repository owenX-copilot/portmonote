package main

import (
	"log"
	"os"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var DB *gorm.DB

func InitDB(dsn string) {
	// Simple Logic: If path starts with .., treat as is.
	// If it's a filename, check if file exists, if not, check parent?
	// Actually, let's keep it simple: Use the provided DSN path.
	// But in main.go we switched to "portmonote.db".
	//
	// In the deployment case: "./portmonote-linux-arm64", we expect "portmonote.db" in CWD.
	// In the dev case: "go run .", we expect "../portmonote.db".

	// Let's implement a fallback strategy here if the file doesn't exist
	// But sqlite.Open will CREATE the file if it doesn't exist, which causes the "Overwrite/Empty" feeling.

	finalDSN := dsn

	// Intelligent Fallback Logic
	// 1. If we asked for "portmonote.db" (current dir), but it's not there...
	// 2. AND "../portmonote.db" (parent dir) DOES exist...
	// 3. Then use the parent one.
	if dsn == "portmonote.db" {
		if _, err := os.Stat(dsn); os.IsNotExist(err) {
			log.Printf("⚠️ Primary database '%s' NOT FOUND in current directory.", dsn)
			if _, err := os.Stat("../portmonote.db"); err == nil {
				finalDSN = "../portmonote.db"
				log.Printf("✅ Found database in parent directory. Switching to fallback: %s", finalDSN)
			} else {
				log.Println("❌ Fallback database '../portmonote.db' also not found. A new empty database will be created.")
			}
		} else {
			log.Printf("✅ Found primary database '%s' in current directory.", dsn)
		}
	} else {
		log.Printf("Using explicit DSN path: %s", dsn)
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
