from flask import Flask, jsonify
import psutil
import socket
import time
import requests
import threading
from datetime import datetime
import subprocess

app = Flask(__name__)

# =====================
# CONFIG
# =====================
BACKEND_BASE_URL = "https://hrl-crms.onrender.com"
REGISTER_URL = f"{BACKEND_BASE_URL}/register_node"
HEARTBEAT_URL = f"{BACKEND_BASE_URL}/agent/heartbeat"

VM_NAME = "windows_10"
RDP_USERNAME = "student"
RDP_PASSWORD = "123"
RDP_PORT = 3389

HEARTBEAT_INTERVAL = 10
POLL_INTERVAL = 5


# =====================
# BASIC UTILITIES
# =====================
def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return socket.gethostbyname(socket.gethostname())


# =====================
# SYSTEM METRICS
# =====================
def get_metrics():
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")

    return {
        "hostname": socket.gethostname(),
        "ip": get_host_ip(),
        "cpu": cpu,
        "memory_used": memory.used,
        "memory_total": memory.total,
        "disk_used": disk.used,
        "disk_total": disk.total
    }


# =====================
# REGISTER NODE
# =====================
def register_node():
    try:
        requests.post(REGISTER_URL,
                      json={"name": socket.gethostname()},
                      timeout=5)
        print("✅ Node registered successfully")
    except Exception as e:
        print("❌ Registration failed:", e)


# =====================
# HEARTBEAT LOOP
# =====================
def heartbeat_loop():
    while True:
        try:
            payload = {
                "timestamp": str(datetime.utcnow()),
                "host": get_metrics()
            }
            requests.post(HEARTBEAT_URL, json=payload, timeout=5)
            print("💓 Heartbeat sent")
        except Exception as e:
            print("❌ Heartbeat error:", e)

        time.sleep(HEARTBEAT_INTERVAL)


# =====================
# VM FUNCTIONS
# =====================
def start_vm():
    print("🚀 Starting VM...")
    subprocess.run(
        ["powershell", "-Command", f"Start-VM -Name '{VM_NAME}'"],
        check=True
    )
    time.sleep(10)  # wait for VM boot


def stop_vm():
    print("🛑 Stopping VM...")
    subprocess.run(
        ["powershell", "-Command", f"Stop-VM -Name '{VM_NAME}' -Force"],
        check=True
    )


def get_vm_ip():
    print("🔎 Getting VM IP...")
    output = subprocess.check_output(
        ["powershell", "-Command",
         f"(Get-VMNetworkAdapter -VMName '{VM_NAME}').IPAddresses"]
    ).decode().strip()

    ips = output.split()

    # Filter only IPv4 addresses
    for ip in ips:
        if "." in ip and not ip.startswith("169."):
            return ip

    raise Exception("No valid VM IP found")


# =====================
# COMMAND POLLING LOOP
# =====================
def command_polling_loop():
    while True:
        try:
            poll_url = f"{BACKEND_BASE_URL}/agent/tasks/poll/{socket.gethostname()}"
            response = requests.get(poll_url, timeout=5)
            data = response.json()

            if data.get("command") == "start_vm":
                task_id = data["task_id"]
                duration = data["duration"]

                try:
                    # 1️⃣ Start VM
                    start_vm()

                    # 2️⃣ Get VM IP
                    vm_ip = get_vm_ip()

                    print(f"✅ VM Started | IP: {vm_ip}")

                    # 3️⃣ Send details to backend
                    ready_url = f"{BACKEND_BASE_URL}/agent/tasks/{task_id}/ready"

                    payload = {
                        "vm_ip": vm_ip,
                        "rdp_link": f"rdp://{vm_ip}:{RDP_PORT}",
                        "username": RDP_USERNAME,
                        "password": RDP_PASSWORD,
                        "port": RDP_PORT
                    }

                    requests.post(ready_url, json=payload, timeout=5)
                    print("📤 VM details sent to backend")

                    # 4️⃣ Auto shutdown after duration
                    threading.Timer(duration * 60, stop_vm).start()
                    print(f"⏳ VM will stop after {duration} minutes")

                except Exception as vm_error:
                    print("❌ VM Start Failed:", vm_error)

                    error_url = f"{BACKEND_BASE_URL}/agent/tasks/{task_id}/error"
                    requests.post(error_url,
                                  json={"reason": str(vm_error)},
                                  timeout=5)

        except Exception as e:
            print("❌ Polling error:", e)

        time.sleep(POLL_INTERVAL)


# =====================
# AGENT HEALTH ENDPOINT
# =====================
@app.route("/agent_health", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "hostname": socket.gethostname(),
        "ip": get_host_ip()
    })


# =====================
# MAIN START
# =====================
if __name__ == "__main__":
    print("===== AGENT STARTING =====")

    register_node()

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=command_polling_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=5000)
