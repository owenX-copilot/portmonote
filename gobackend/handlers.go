package main

import (
	"log"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

var CSRF_TOKEN string

func InitHandlers(r *gin.Engine) {
	// Generate CSRF Token on startup
	CSRF_TOKEN = uuid.New().String()
	log.Printf("CSRF Token: %s", CSRF_TOKEN)

	// Middleware for CSRF
	r.Use(func(c *gin.Context) {
		// Public routes
		if c.Request.Method == "GET" || c.Request.URL.Path == "/" {
			c.Next()
			return
		}

		// Verify Token
		token := c.GetHeader("X-CSRF-Token")
		if token != CSRF_TOKEN {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "Invalid CSRF Token. Refresh page."})
			return
		}
		c.Next()
	})

	// Routes
	r.GET("/", handleIndex)
	r.GET("/favicon.ico", handleFavicon)

	r.GET("/ports", getPorts)
	r.GET("/history", getHistory)
	r.POST("/notes", updateNote)
	r.DELETE("/ports", deletePort)
	r.POST("/acknowledge", acknowledgeWarning)
	r.POST("/trigger-scan", triggerScan)
	r.GET("/inspect/:port", runWitr)
}

func handleFavicon(c *gin.Context) {
	// Try current folder
	if _, err := os.Stat("frontend/favicon.ico"); err == nil {
		c.File("frontend/favicon.ico")
		return
	}
	c.Status(http.StatusNotFound)
}

func handleIndex(c *gin.Context) {
	var content []byte
	var err error

	// Read from external file only
	content, err = os.ReadFile("frontend/index.html")

	if err != nil {
		c.String(http.StatusNotFound, "Frontend not found")
		return
	}

	if err != nil {
		c.String(http.StatusInternalServerError, "Error loading frontend: index.html not found in binary or 'frontend/' folder.")
		return
	}

	// Inject Token
	html := string(content)
	injection := `<script>window.PORTMONOTE_CSRF_TOKEN = "` + CSRF_TOKEN + `";</script>`
	if strings.Contains(html, "<head>") {
		html = strings.Replace(html, "<head>", "<head>\n"+injection, 1)
	} else {
		html = injection + html
	}

	c.Header("Content-Type", "text/html")
	c.String(http.StatusOK, html)
}

func getPorts(c *gin.Context) {
	var runtimes []PortRuntime
	var notes []PortNote

	DB.Find(&runtimes)
	DB.Find(&notes)

	// Merge logic (host_id, protocol, port)
	// Similar to Python map logic
	mergedMap := make(map[string]*MergedPortItem)

	// 1. Process Runtimes
	for _, r := range runtimes {
		key := fmtKey(r.HostID, r.Protocol, r.Port)
		item := &MergedPortItem{
			HostID: r.HostID, Protocol: r.Protocol, Port: r.Port,
			RuntimeID:         r.ID,
			FirstSeenAt:       &r.FirstSeenAt,
			LastSeenAt:        &r.LastSeenAt,
			LastDisappearedAt: r.LastDisappearedAt,
			CurrentState:      r.CurrentState,
			CurrentPID:        r.CurrentPID,
			ProcessName:       r.ProcessName,
			Cmdline:           r.Cmdline,
			RiskLevel:         "unknown",
			DerivedStatus:     "unknown",
		}
		mergedMap[key] = item
	}

	// 2. Process Notes
	for _, n := range notes {
		key := fmtKey(n.HostID, n.Protocol, n.Port)
		if item, exists := mergedMap[key]; exists {
			item.NoteID = n.ID
			item.Title = n.Title
			item.Description = n.Description
			item.Owner = n.Owner
			item.RiskLevel = n.RiskLevel
			item.IsPinned = n.IsPinned
		} else {
			// Note without runtime (Ghost/Forgotten)
			mergedMap[key] = &MergedPortItem{
				HostID: n.HostID, Protocol: n.Protocol, Port: n.Port,
				NoteID:        n.ID,
				Title:         n.Title,
				Description:   n.Description,
				Owner:         n.Owner,
				RiskLevel:     n.RiskLevel,
				IsPinned:      n.IsPinned,
				DerivedStatus: "unknown",
			}
		}
	}

	// 3. Finalize Status & Events
	result := make([]MergedPortItem, 0, len(mergedMap))
	for _, item := range mergedMap {
		calculateStatus(item)
		// Get latest event type (lazy load or join query preferred, but simple loop ok for small tool)
		if item.RuntimeID != 0 {
			var evt PortEvent
			// Get latest event
			if err := DB.Where("port_runtime_id = ?", item.RuntimeID).Order("timestamp desc").First(&evt).Error; err == nil {
				item.LatestEventType = evt.EventType
				item.LatestEventTimestamp = &evt.Timestamp
			}
		}
		result = append(result, *item)
	}

	c.JSON(http.StatusOK, result)
}

func getHistory(c *gin.Context) {
	hostID := c.Query("host_id")
	proto := c.Query("protocol")
	portStr := c.Query("port")
	port, _ := strconv.Atoi(portStr)

	// Find runtime
	var runtime PortRuntime
	if err := DB.Where("host_id = ? AND protocol = ? AND port = ?", hostID, proto, port).First(&runtime).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Runtime not found"})
		return
	}

	var events []PortEvent
	DB.Where("port_runtime_id = ?", runtime.ID).Order("timestamp desc").Find(&events)
	c.JSON(http.StatusOK, events)
}

func updateNote(c *gin.Context) {
	hostID := c.Query("host_id")
	proto := c.Query("protocol")
	portStr := c.Query("port")
	port, _ := strconv.Atoi(portStr)

	var req NoteUpdateRequest
	if err := c.BindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	var note PortNote
	err := DB.Where("host_id = ? AND protocol = ? AND port = ?", hostID, proto, port).First(&note).Error

	if err != nil {
		// Create new
		note = PortNote{
			HostID: hostID, Protocol: proto, Port: port,
			RiskLevel: "expected", // Default
		}
	}

	// Apply updates
	if req.Title != nil {
		note.Title = *req.Title
	}
	if req.Description != nil {
		note.Description = *req.Description
	}
	if req.Owner != nil {
		note.Owner = *req.Owner
	}
	if req.RiskLevel != nil {
		note.RiskLevel = *req.RiskLevel
	}
	if req.IsPinned != nil {
		note.IsPinned = *req.IsPinned
	}

	DB.Save(&note)
	c.JSON(http.StatusOK, note)
}

func deletePort(c *gin.Context) {
	hostID := c.Query("host_id")
	proto := c.Query("protocol")
	portStr := c.Query("port")
	port, _ := strconv.Atoi(portStr)

	// Delete Runtime
	DB.Where("host_id = ? AND protocol = ? AND port = ?", hostID, proto, port).Delete(&PortRuntime{})
	// Delete Note
	DB.Where("host_id = ? AND protocol = ? AND port = ?", hostID, proto, port).Delete(&PortNote{})

	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

func acknowledgeWarning(c *gin.Context) {
	hostID := c.Query("host_id")
	proto := c.Query("protocol")
	portStr := c.Query("port")
	port, _ := strconv.Atoi(portStr)

	var runtime PortRuntime
	if err := DB.Where("host_id = ? AND protocol = ? AND port = ?", hostID, proto, port).First(&runtime).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "Runtime not found"})
		return
	}

	// Add Acknowledged Event
	evt := PortEvent{
		PortRuntimeID: runtime.ID,
		EventType:     "acknowledged",
		Timestamp:     time.Now(),
		PID:           runtime.CurrentPID,
		ProcessName:   runtime.ProcessName,
	}
	DB.Create(&evt)
	c.JSON(http.StatusOK, gin.H{"status": "acknowledged"})
}

func triggerScan(c *gin.Context) {
	go RunCollectionCycle()
	c.JSON(http.StatusOK, gin.H{"status": "triggered"})
}

func runWitr(c *gin.Context) {
	portStr := c.Param("port")
	// Use exec.Command
	// Security: Validate port is integer
	if _, err := strconv.Atoi(portStr); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid port"})
		return
	}

	path, err := exec.LookPath("witr")
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"output": "witr not found on path", "error": true})
		return
	}

	cmd := exec.Command(path, "--port", portStr)
	// Timeout logic?
	out, err := cmd.CombinedOutput()
	output := string(out)
	if err != nil {
		output += "\nError: " + err.Error()
	}

	// Save to History (DB)
	// 1. Find active runtime for this port (HostID=local, Protocol=?, Port=?)
	// Note: runWitr assumes TCP/UDP? Witr tool usually autodetects or we assume from context.
	// Since runWitr param is only :port, we might have ambiguity if same port on tcp/udp.
	// But usually it's unique enough or we pick the first active one.
	portNum, _ := strconv.Atoi(portStr)
	var runtime PortRuntime
	// Try to find the active runtime associated with this port
	if err := DB.Where("host_id = ? AND port = ? AND current_state = ?", "local", portNum, "active").First(&runtime).Error; err == nil {
		// Create Event
		evt := PortEvent{
			PortRuntimeID: runtime.ID,
			EventType:     string(EventDiagnosis),
			Timestamp:     time.Now(),
			PID:           runtime.CurrentPID,
			ProcessName:   runtime.ProcessName,
			WitrOutput:    output,
		}
		DB.Create(&evt)
	} else {
		// Log error or ignore if not found (maybe ghost port?)
		log.Printf("Could not log witr event for port %d: %v", portNum, err)
	}

	c.JSON(http.StatusOK, gin.H{"output": output, "error": err != nil})
}

// Helpers
func fmtKey(h, p string, port int) string {
	return h + "_" + p + "_" + strconv.Itoa(port)
}

func calculateStatus(item *MergedPortItem) {
	item.DerivedStatus = "active" // Default

	isActive := item.CurrentState == "active"
	isDisappeared := item.CurrentState == "disappeared"
	hasNote := item.NoteID != 0
	isTrusted := hasNote && item.RiskLevel == "trusted"

	if isActive {
		if isTrusted {
			item.DerivedStatus = "healthy"
			return
		}
		if !hasNote {
			item.DerivedStatus = "suspicious"
			return
		}
		if item.RiskLevel == "suspicious" {
			item.DerivedStatus = "suspicious"
			return
		}
		item.DerivedStatus = "healthy" // Default active+note
	} else if isDisappeared {
		// ghost logic
		item.DerivedStatus = "ghost"
	}
}
