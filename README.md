# Server Monitoring for Home Assistant

Single Docker container that monitors your server and publishes to MQTT with Home Assistant auto-discovery.

For Homeassistant Docker running on Linux onlu!

## Features

- **Glances** - Host-level CPU, RAM, disk, network via web API
- **Container monitoring** - Status, health, CPU%, memory%, disk size, restarts
- **Error detection** - Scans container logs for ERROR/CRITICAL (not warnings)
- **System updates** - Counts available apt updates, trigger upgrades via MQTT
- **Kernel errors** - Monitors dmesg for I/O and NVMe errors
- **Auto-discovery** - Sensors automatically appear in Home Assistant

## Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/kattcrazy/server-statistics.git
   cd server-statistics
   ```

2. Copy `.env.example` to `.env` and configure:
   ```bash
   cp .env.example .env
   nano .env  # Edit with your MQTT settings
   ```

3. Build and run:
   ```bash
   docker compose up -d --build
   ```

4. In Home Assistant:
   - **Glances**: Settings → Integrations → Add → Glances (host: your-server-ip, port: 61208)
   - **MQTT sensors**: Automatically discovered under device "Server Monitor"

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MQTT_HOST` | Yes | - | MQTT broker IP/hostname |
| `MQTT_PORT` | No | 1883 | MQTT broker port |
| `MQTT_USER` | Yes | - | MQTT username |
| `MQTT_PASSWORD` | Yes | - | MQTT password |
| `TOPIC_PREFIX` | No | server | MQTT topic prefix |
| `LOOP_INTERVAL` | No | 300 | Check interval in seconds |
| `TZ` | No | America/Los_Angeles | Timezone |
| `GLANCES_PORT` | No | 61208 | Glances web UI port |

## MQTT Topics

### Per-container (auto-discovered)
- `{prefix}/containers/{name}/status` - up/down
- `{prefix}/containers/{name}/health` - healthy/unhealthy/none
- `{prefix}/containers/{name}/cpu_percent` - CPU %
- `{prefix}/containers/{name}/mem_percent` - Memory %
- `{prefix}/containers/{name}/mem_usage` - Memory usage string
- `{prefix}/containers/{name}/disk_size` - Container disk size
- `{prefix}/containers/{name}/restart_count` - Restart count
- `{prefix}/containers/{name}/error_count` - Errors in last 5 min
- `{prefix}/containers/{name}/last_error` - Most recent error (persists)
- `{prefix}/containers/{name}/last_error_level` - ERROR/CRITICAL/NONE

### Server-wide (auto-discovered)
- `{prefix}/updates/count` - Available apt updates
- `{prefix}/updates/status` - idle/running/done/failed
- `{prefix}/updates/trigger` - Publish "run" to trigger apt upgrade
- `{prefix}/system/io_error_count` - Kernel I/O errors
- `{prefix}/system/last_io_error` - Most recent I/O error

## Home Assistant Entities

### MQTT Sensors (auto-discovered)
After starting, these entities auto-appear under device "Server Monitor":
- `sensor.*_status`, `sensor.*_health`, `sensor.*_cpu`, etc. for each container
- `sensor.updates_available`, `sensor.update_status`
- `sensor.io_errors`, `sensor.last_io_error`
- `button.run_server_updates` - Triggers apt upgrade

### Glances Integration Entities
Add via: Settings → Integrations → Add → Glances (host: your-server-ip, port: 61208)

| Entity | Description |
|--------|-------------|
| `sensor.*_cpu_used` | CPU usage % |
| `sensor.*_ram_used` | RAM usage % |
| `sensor.*_ram_used_percent` | RAM usage in bytes |
| `sensor.*_swap_used` | Swap usage % |
| `sensor.*_disk_used_*` | Disk usage % per mount |
| `sensor.*_disk_free_*` | Disk free space per mount |
| `sensor.*_network_rx_*` | Network receive rate (bytes/s) |
| `sensor.*_network_tx_*` | Network transmit rate (bytes/s) |
| `sensor.*_load_1min` | 1-minute load average |
| `sensor.*_load_5min` | 5-minute load average |
| `sensor.*_load_15min` | 15-minute load average |
| `sensor.*_uptime` | System uptime |
| `sensor.*_cpu_thermal` | CPU temperature (if available) |

*Note: Entity names are prefixed with your Glances integration name (e.g., `sensor.server_cpu_used`)*

## Requirements

- Docker with docker compose
- MQTT broker (e.g., Mosquitto)
- Home Assistant with MQTT & Glances integration
