package main

import (
	"log"
	"time"

	"github.com/shirou/gopsutil/v4/net"
	"github.com/shirou/gopsutil/v4/process"
)

type PortKey struct {
	HostID   string
	Protocol string
	Port     int
}

type ScanResult struct {
	PID         int
	ProcessName string
	Cmdline     string
	State       string // LISTEN, ESTABLISHED, etc.
}

// Global host ID
const HostID = "local"

func RunCollectionCycle() {
	log.Println("Starting collection cycle...")

	// 1. Scan Current Ports
	currentOpenPorts, err := scanPorts()
	if err != nil {
		log.Println("Error scanning ports:", err)
		return
	}

	// 2. Load DB State (Active Runtimes)
	var activeRuntimes []PortRuntime
	// Get all runtimes that are currently tracked
	if err := DB.Find(&activeRuntimes).Error; err != nil {
		log.Println("Error loading runtimes:", err)
		return
	}

	// Turn DB list into Map for fast lookup
	dbMap := make(map[PortKey]*PortRuntime)
	for i := range activeRuntimes {
		r := &activeRuntimes[i]
		key := PortKey{HostID: r.HostID, Protocol: r.Protocol, Port: r.Port}
		dbMap[key] = r
	}

	// 3. Process Appearances and Updates
	seenKeys := make(map[PortKey]bool)

	for key, scanRes := range currentOpenPorts {
		seenKeys[key] = true

		runtime, exists := dbMap[key]

		if !exists {
			// NEW PORT APPEARED
			newRuntime := PortRuntime{
				HostID:         key.HostID,
				Protocol:       key.Protocol,
				Port:           key.Port,
				FirstSeenAt:    time.Now(),
				LastSeenAt:     time.Now(),
				CurrentState:   string(StateActive),
				CurrentPID:     scanRes.PID,
				ProcessName:    scanRes.ProcessName,
				Cmdline:        scanRes.Cmdline,
				TotalSeenCount: 1,
			}
			DB.Create(&newRuntime)

			// Log Event: Appeared
			DB.Create(&PortEvent{
				PortRuntimeID: newRuntime.ID,
				EventType:     string(EventAppeared),
				Timestamp:     time.Now(),
				PID:           scanRes.PID,
				ProcessName:   scanRes.ProcessName,
			})

		} else {
			// EXISTING PORT
			// Check for Process Change (Hijack detection)
			// Only if it was active and process name changed significantly
			if runtime.CurrentState == string(StateActive) &&
				runtime.ProcessName != "" &&
				scanRes.ProcessName != "" &&
				runtime.ProcessName != scanRes.ProcessName {

				// Log Event: Process Change
				log.Printf("Process Change Detected on Port %d: %s -> %s", key.Port, runtime.ProcessName, scanRes.ProcessName)
				DB.Create(&PortEvent{
					PortRuntimeID: runtime.ID,
					EventType:     string(EventProcessChange),
					Timestamp:     time.Now(),
					PID:           scanRes.PID,
					ProcessName:   scanRes.ProcessName,
				})
			}

			// Update Runtime
			runtime.LastSeenAt = time.Now()
			runtime.CurrentState = string(StateActive)
			runtime.CurrentPID = scanRes.PID
			runtime.ProcessName = scanRes.ProcessName
			runtime.Cmdline = scanRes.Cmdline
			runtime.TotalSeenCount++

			// Calculate Uptime (approx)
			uptime := runtime.LastSeenAt.Sub(runtime.FirstSeenAt).Seconds()
			runtime.TotalUptimeSeconds = int(uptime)

			DB.Save(runtime)
		}
	}

	// 4. Process Disappearances
	for key, runtime := range dbMap {
		if !seenKeys[key] {
			// It was in DB, but not in current scan -> Disappeared
			if runtime.CurrentState == string(StateActive) {
				runtime.CurrentState = string(StateDisappeared)
				now := time.Now()
				runtime.LastDisappearedAt = &now
				DB.Save(runtime)

				// Log Event: Disappeared
				DB.Create(&PortEvent{
					PortRuntimeID: runtime.ID,
					EventType:     string(EventDisappeared),
					Timestamp:     time.Now(),
					PID:           runtime.CurrentPID,
					ProcessName:   runtime.ProcessName,
				})
			}
		}
	}

	log.Println("Cycle complete.")
}

func scanPorts() (map[PortKey]ScanResult, error) {
	results := make(map[PortKey]ScanResult)

	// Get Connections (inet, all protocols)
	conns, err := net.Connections("inet")
	if err != nil {
		return nil, err
	}

	for _, c := range conns {
		// Filter only LISTEN for TCP, and maybe establish for others if needed, usually monitor LISTEN
		isListen := c.Status == "LISTEN"
		// For UDP, status is usually blank/NONE, treat as open
		isUDP := c.Type == 2 // SOCK_DGRAM

		if !isListen && !isUDP {
			continue
		}

		pid := int(c.Pid)
		if pid == 0 {
			continue // System idle or permission denied
		}

		procName := ""
		cmdLine := ""

		// Get Process Info
		if p, err := process.NewProcess(int32(pid)); err == nil {
			procName, _ = p.Name()
			cmdLine, _ = p.Cmdline()
		}

		protocol := "tcp"
		if isUDP {
			protocol = "udp"
		}

		key := PortKey{
			HostID:   HostID,
			Protocol: protocol,
			Port:     int(c.Laddr.Port),
		}

		results[key] = ScanResult{
			PID:         pid,
			ProcessName: procName,
			Cmdline:     cmdLine,
			State:       c.Status,
		}
	}

	return results, nil
}
