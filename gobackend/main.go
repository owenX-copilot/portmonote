package main

import (
	"log"
	"path/filepath"
	"time"

	"github.com/gin-gonic/gin"
)

func main() {
	// 1. Initialize DB
	// Point to the potentially existing DB in the project root
	InitDB("../portmonote.db")

	// 2. Start Collector (Background)
	go func() {
		// Run immediately
		RunCollectionCycle()

		// Run every 1 minute
		ticker := time.NewTicker(1 * time.Minute)
		for range ticker.C {
			RunCollectionCycle()
		}
	}()

	// 3. Setup Web Server
	r := gin.Default()

	// Serve Static Files (Frontend assets except index.html)
	// We handle index.html manually for CSRF injection
	// Assuming frontend has other assets? Currently it seems just index.html.
	// If frontend has css/js files:
	frontendPath := "../frontend"
	r.Static("/static", filepath.Join(frontendPath, "static")) // If any

	// Register API Routes
	InitHandlers(r) // Defined in handlers.go

	// Start Server
	log.Println("Portmonote Go Backend running on :2008")
	if err := r.Run(":2008"); err != nil {
		log.Fatal(err)
	}
}
