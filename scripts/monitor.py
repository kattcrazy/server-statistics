#!/usr/bin/env python3
"""
Server monitoring: Docker container logs, disk, health, system updates, kernel I/O errors.
Publishes to MQTT. Subscribes to server/updates/trigger for apt upgrade.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import docker
import paho.mqtt.client as mqtt

from config import (
    MQTT_HOST,
    MQTT_PORT,
    MQTT_USER,
    MQTT_PASSWORD,
    TOPIC_PREFIX,
    ERROR_KEYWORDS,
    KERNEL_ERROR_KEYWORDS,
    LOOP_INTERVAL,
)

# MQTT client
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD if MQTT_PASSWORD else None)
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()

# Docker client
docker_client = docker.from_env()

# Update trigger flag
update_triggered = False

# Track discovered containers for HA auto-discovery
discovered_containers = set()
discovery_published = False
# Track containers that have had errors (so we don't overwrite with NONE)
containers_with_errors = set()

DEVICE_INFO = {
    "identifiers": ["server_monitor"],
    "name": "Server Monitor",
    "manufacturer": "Custom",
    "model": "Docker Monitor",
}


def publish_discovery(component: str, object_id: str, config: dict):
    """Publish Home Assistant MQTT discovery config."""
    topic = f"homeassistant/{component}/{object_id}/config"
    config["device"] = DEVICE_INFO
    client.publish(topic, json.dumps(config), retain=True)


def publish_container_discovery(name: str):
    """Publish HA discovery for a container's sensors."""
    if name in discovered_containers:
        return
    discovered_containers.add(name)
    
    safe_name = name.replace("-", "_").replace(".", "_")
    
    sensors = [
        ("status", "Status", None, "mdi:docker", None),
        ("health", "Health", None, "mdi:heart-pulse", None),
        ("cpu_percent", "CPU", "%", "mdi:cpu-64-bit", None),
        ("mem_percent", "Memory", "%", "mdi:memory", None),
        ("mem_usage", "Memory Usage", None, "mdi:memory", None),
        ("disk_size", "Disk Size", None, "mdi:harddisk", None),
        ("restart_count", "Restarts", None, "mdi:restart", None),
        ("error_count", "Errors", None, "mdi:alert-circle", None),
        ("last_error", "Last Error", None, "mdi:alert", "{{ value_json.msg[:200] if value_json.msg and value_json.msg != 'none' else 'none' }}"),
        ("last_error_level", "Error Level", None, "mdi:alert-octagram", None),
    ]
    
    for suffix, label, unit, icon, tpl in sensors:
        object_id = f"container_{safe_name}_{suffix}"
        config = {
            "name": f"{name} {label}",
            "state_topic": f"{TOPIC_PREFIX}/containers/{name}/{suffix}",
            "unique_id": object_id,
            "icon": icon,
        }
        if unit:
            config["unit_of_measurement"] = unit
        if tpl:
            config["value_template"] = tpl
        publish_discovery("sensor", object_id, config)


def publish_system_discovery():
    """Publish HA discovery for system-level sensors."""
    global discovery_published
    if discovery_published:
        return
    discovery_published = True
    
    sensors = [
        ("updates_count", "Updates Available", "server/updates/count", None, "mdi:package-up", None),
        ("updates_status", "Update Status", "server/updates/status", None, "mdi:package-check", None),
        ("io_error_count", "IO Errors", "server/system/io_error_count", None, "mdi:harddisk-remove", None),
        ("last_io_error", "Last IO Error", "server/system/last_io_error", None, "mdi:alert-octagon", "{{ value_json.msg[:200] if value_json.msg and value_json.msg != 'none' else 'none' }}"),
    ]
    
    for object_id, name, state_topic, unit, icon, tpl in sensors:
        config = {
            "name": name,
            "state_topic": state_topic,
            "unique_id": f"server_{object_id}",
            "icon": icon,
        }
        if unit:
            config["unit_of_measurement"] = unit
        if tpl:
            config["value_template"] = tpl
        publish_discovery("sensor", f"server_{object_id}", config)
    
    # Button entity for triggering updates
    publish_discovery("button", "server_run_updates", {
        "name": "Run Server Updates",
        "unique_id": "server_run_updates",
        "command_topic": f"{TOPIC_PREFIX}/updates/trigger",
        "payload_press": "run",
        "icon": "mdi:update",
    })
    
    # Publish initial values for server-wide sensors
    mqtt_publish("updates/status", "idle")
    mqtt_publish("system/last_io_error", {"msg": "none", "timestamp": ""})
    mqtt_publish("system/io_error_count", 0)


def mqtt_publish(topic: str, payload: str | int | dict):
    """Publish to MQTT."""
    if isinstance(payload, dict):
        payload = json.dumps(payload)
    elif isinstance(payload, int):
        payload = str(payload)
    client.publish(f"{TOPIC_PREFIX}/{topic}", payload, retain=True)


def get_containers():
    """Auto-discover all containers (including stopped)."""
    try:
        return [c.name for c in docker_client.containers.list(all=True)]
    except Exception as e:
        print(f"Error listing containers: {e}", file=sys.stderr)
        return []


def check_container_logs():
    """Scan docker logs for errors, publish to MQTT."""
    for name in get_containers():
        publish_container_discovery(name)
        try:
            container = docker_client.containers.get(name)
            logs = container.logs(since=300, stderr=True, stdout=True).decode(errors="replace")
        except Exception as e:
            mqtt_publish(f"containers/{name}/last_error", {"level": "ERROR", "msg": str(e)})
            continue

        errors = []
        for line in logs.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip ANSI color codes for cleaner matching and display
            clean_line = re.sub(r'\x1b\[[0-9;]*m|D\[[0-9;]*m|\[\d+m', '', line)
            
            matched = False
            level = "ERROR"
            for kw in ERROR_KEYWORDS:
                if kw.lower() in clean_line.lower():
                    matched = True
                    break
            
            if not matched:
                continue
                
            # Skip warnings - only keep ERROR and CRITICAL
            if re.search(r'\bWARN(ING)?\b|\bWRN\b|level[=:]warn|\[WARN', clean_line, re.I):
                continue
            
            # Determine level - check CRITICAL first
            if re.search(r'\bCRITICAL\b|\bFATAL\b|level[=:]critical|"level"\s*:\s*"critical"', clean_line, re.I):
                level = "CRITICAL"
            elif re.search(r'\bERROR\b|level[=:]error|"level"\s*:\s*"error"|Exception|Traceback', clean_line, re.I):
                level = "ERROR"
            
            errors.append({"level": level, "msg": clean_line[:500], "timestamp": datetime.now(timezone.utc).isoformat()})

        mqtt_publish(f"containers/{name}/error_count", len(errors))
        if errors:
            containers_with_errors.add(name)
            mqtt_publish(f"containers/{name}/last_error", {"level": errors[-1]["level"], "msg": errors[-1]["msg"]})
            mqtt_publish(f"containers/{name}/last_error_level", errors[-1]["level"])
            mqtt_publish(f"containers/{name}/errors", json.dumps(errors[-5:]))
        elif name not in containers_with_errors:
            # Only publish NONE if container has never had errors (don't overwrite persisted errors)
            mqtt_publish(f"containers/{name}/last_error", {"level": "NONE", "msg": "none"})
            mqtt_publish(f"containers/{name}/last_error_level", "NONE")


def check_container_disk():
    """Get per-container disk size via docker ps -s (run docker:cli container), publish to MQTT."""
    try:
        result = docker_client.containers.run(
            "docker:cli",
            ["docker", "ps", "-a", "-s", "--format", "{{.Names}} {{.Size}}"],
            remove=True,
            volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}},
            user="root",
            detach=False,
        )
        stdout = result.decode() if isinstance(result, bytes) else result
    except Exception as e:
        print(f"Error getting container disk: {e}", file=sys.stderr)
        return

    for line in stdout.strip().splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) != 2:
            continue
        name, size_info = parts
        # size_info is like "1.16MB (virtual 155MB)" - use first value
        disk_size = size_info.split()[0] if size_info else "0B"
        mqtt_publish(f"containers/{name}/disk_size", disk_size)


def check_container_stats():
    """Publish per-container CPU and RAM (Glances containers plugin returns empty)."""
    try:
        result = docker_client.containers.run(
            "docker:cli",
            [
                "docker", "stats", "--no-stream", "--format",
                "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}\t{{.MemUsage}}"
            ],
            remove=True,
            volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}},
            user="root",
            detach=False,
        )
        stdout = result.decode() if isinstance(result, bytes) else result
    except Exception as e:
        print(f"Error getting container stats: {e}", file=sys.stderr)
        return
    for line in stdout.strip().splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue
        name, cpu_pct, mem_pct, mem_usage = parts[0], parts[1], parts[2], parts[3]
        cpu_pct = cpu_pct.rstrip("%") or "0"
        mem_pct = mem_pct.rstrip("%") or "0"
        mqtt_publish(f"containers/{name}/cpu_percent", float(cpu_pct) if cpu_pct.replace(".", "").isdigit() else 0)
        mqtt_publish(f"containers/{name}/mem_percent", float(mem_pct) if mem_pct.replace(".", "").isdigit() else 0)
        mqtt_publish(f"containers/{name}/mem_usage", mem_usage)


def check_container_health():
    """Publish container status (up/down), health (healthy/unhealthy), and restart count."""
    try:
        for c in docker_client.containers.list(all=True):
            name = c.name
            try:
                inspect = docker_client.api.inspect_container(c.id)
                state = inspect["State"]
                raw_status = state.get("Status", "unknown")
                status = "up" if raw_status == "running" else "down"
                health = state.get("Health", {}).get("Status", "none")
                if health not in ("healthy", "unhealthy", "starting"):
                    health = "none"
                restart_count = state.get("RestartCount", 0)
            except Exception:
                status = "down"
                health = "none"
                restart_count = 0
            mqtt_publish(f"containers/{name}/status", status)
            mqtt_publish(f"containers/{name}/health", health)
            mqtt_publish(f"containers/{name}/restart_count", restart_count)
    except Exception as e:
        print(f"Error checking container health: {e}", file=sys.stderr)


def check_updates():
    """Run apt list --upgradable via chroot, publish count."""
    try:
        result = docker_client.containers.run(
            "ubuntu:22.04",
            ["bash", "-c", "chroot /host apt list --upgradable 2>/dev/null | grep -c upgradable || true"],
            remove=True,
            volumes={"/": {"bind": "/host", "mode": "ro"}},
            network_mode="host",
            user="root",
            detach=False,
        )
        count = int(result.decode().strip().splitlines()[-1] if result else 0)
    except Exception as e:
        print(f"Error checking updates: {e}", file=sys.stderr)
        count = 0
    mqtt_publish("updates/count", count)


def run_apt_upgrade():
    """Run apt upgrade on host via chroot."""
    mqtt_publish("updates/status", "running")
    try:
        docker_client.containers.run(
            "ubuntu:22.04",
            [
                "bash", "-c",
                "export DEBIAN_FRONTEND=noninteractive && "
                "chroot /host apt-get update && "
                "chroot /host apt-get -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-conffold upgrade -y"
            ],
            remove=True,
            volumes={"/": {"bind": "/host", "mode": "rw"}},
            network_mode="host",
            user="root",
            detach=False,
        )
        mqtt_publish("updates/status", "done")
    except Exception as e:
        mqtt_publish("updates/status", f"failed: {str(e)[:200]}")


def check_kernel_errors():
    """Run dmesg, grep for I/O/NVMe errors, publish to MQTT."""
    try:
        result = subprocess.run(
            ["dmesg", "-T"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        print(f"Error running dmesg: {e}", file=sys.stderr)
        mqtt_publish("system/io_error_count", 0)
        return

    if result.returncode != 0:
        mqtt_publish("system/io_error_count", 0)
        return

    matches = []
    for line in result.stdout.splitlines():
        for kw in KERNEL_ERROR_KEYWORDS:
            if kw in line:
                matches.append({"msg": line[:500], "timestamp": datetime.now(timezone.utc).isoformat()})
                break

    mqtt_publish("system/io_error_count", len(matches))
    if matches:
        mqtt_publish("system/last_io_error", matches[-1])
        mqtt_publish("system/kernel_errors", json.dumps(matches[-10:]))


def on_message(_, userdata, msg):
    """Handle MQTT messages for update trigger."""
    global update_triggered
    if msg.topic == f"{TOPIC_PREFIX}/updates/trigger":
        payload = msg.payload.decode()
        if payload in ("run", "1", "true"):
            update_triggered = True


client.subscribe(f"{TOPIC_PREFIX}/updates/trigger")
client.on_message = on_message


def main():
    global update_triggered
    print("Monitor started. Loop interval:", LOOP_INTERVAL, "seconds")
    publish_system_discovery()
    while True:
        try:
            if update_triggered:
                update_triggered = False
                run_apt_upgrade()

            check_container_logs()
            check_container_disk()
            check_container_stats()
            check_container_health()
            check_updates()
            check_kernel_errors()
        except Exception as e:
            print(f"Loop error: {e}", file=sys.stderr)

        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
