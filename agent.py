from flask import Flask, jsonify, request
import psutil
import socket
import time
import requests
import threading
from datetime import datetime
import subprocess

app = Flask(__name__)

# ===================== CONFIG =====================
BACKEND_BASE_URL = "https://hrl-crms.onrender.com"
REGISTER_URL = f"{BACKEND_BASE_URL}/register_node"
HEARTBEAT_URL = f"{BACKEND_BASE_URL}/agent/heartbeat"
HEARTBEAT_INTERVAL = 10  # seconds

VM_NAME = "windows_10"
RDP_USERNAME = "student"
RDP_PASSWORD = "123"
RDP_PORT = 3389

# ===================== UTILS =====================
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return socket.gethostbyname(socket.gethostname())

# ===================== METRICS =====================
def get_host_metrics():
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    return {
        "hostname": socket.gethostname(),
        "cpu": {"used_percent": cpu_percent},  # dictionary for backend
        "memory": {
            "total": memory.total,
            "used": memory.used,
            "free": memory.available
        },
        "storage": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free
        },
        "ip": get_ip()
    }

def build_payload():
    return {
        "timestamp": str(datetime.utcnow()),
        "host": get_host_metrics()
    }

# ===================== NODE REGISTRATION =====================
def register_node():
    try:
        requests.post(REGISTER_URL, json={"name": socket.gethostname()}, timeout=10)
        print("✅ Node registered successfully")
    except Exception as e:
        print("❌ Register failed:", e)

# ===================== HEARTBEAT LOOP =====================
def heartbeat_loop():
    while True:
        try:
            requests.post(HEARTBEAT_URL, json=build_payload(), timeout=10)
            print("💓 Heartbeat sent")
        except Exception as e:
            print("❌ Heartbeat failed:", e)
        time.sleep(HEARTBEAT_INTERVAL)

# ===================== COMMAND POLLING LOOP =====================
def command_polling_loop():
    while True:
        try:
            poll_url = f"{BACKEND_BASE_URL}/agent/tasks/poll/{socket.gethostname()}"
            r = requests.get(poll_url, timeout=15)  # increased timeout
            data = r.json()

            if data.get("command") == "start_vm":
                task_id = data["task_id"]
                duration = data.get("duration", 30)  # default 30 min
                mode = data.get("mode", "remote")

                # Start VM
                print(f"🔄 Starting VM '{VM_NAME}' for task {task_id}")
                subprocess.run(["powershell", "-Command", f"Start-VM -Name '{VM_NAME}'"], check=True)

                # Get VM IP
                ip_output = subprocess.check_output([
                    "powershell",
                    "-Command",
                    f"(Get-VMNetworkAdapter -VMName '{VM_NAME}').IPAddresses"
                ]).decode().strip()
                vm_ip = ip_output.split()[0]  # first IP

                # Send ready info to backend
                ready_url = f"{BACKEND_BASE_URL}/agent/tasks/{task_id}/ready"
                payload = {
                    "rdp_link": f"rdp://{vm_ip}:{RDP_PORT}",
                    "username": RDP_USERNAME,
                    "password": RDP_PASSWORD,
                    "port": RDP_PORT
                }
                requests.post(ready_url, json=payload, timeout=15)
                print(f"✅ VM info sent to backend for task {task_id}")

                # Schedule automatic shutdown
                threading.Timer(duration * 60, lambda: subprocess.run(
                    ["powershell", "-Command", f"Stop-VM -Name '{VM_NAME}' -Force"]
                )).start()
                print(f"⏳ VM scheduled to stop after {duration} minutes")

        except Exception as e:
            print("❌ Polling error:", e)

        time.sleep(5)

# ===================== AGENT HEALTH =====================
@app.route("/agent_health", methods=["GET"])
def agent_health():
    return jsonify({
        "status": "running",
        "hostname": socket.gethostname(),
        "ip": get_ip()
    })

# ===================== HOST RDP INFO =====================
@app.route("/agent/rdp/host", methods=["GET"])
def host_rdp():
    return jsonify({
        "type": "host",
        "hostname": socket.gethostname(),
        "ip": get_ip(),
        "username": RDP_USERNAME,
        "password": RDP_PASSWORD,
        "port": RDP_PORT
    })

# ===================== START AGENT =====================
if __name__ == "__main__":
    register_node()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=command_polling_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)

