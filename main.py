import socket
import platform
import getpass
import subprocess

def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]

    except OSError:
        return "Немає мережевого з'єднання"

    finally:
        sock.close()

def get_network_interfaces():
    try:
        result = subprocess.run(
            ["ip", "-brief", "address"],
            capture_output=True,
            text=True,
            check=True
        )

        return result.stdout

    except subprocess.CalledProcessError:
        return "Не вдалося отримати мережеві інтерфейси"

def get_interface_type(name):
    if name.startswith("wl"):
        return "Wi-Fi"
    elif name.startswith("wwan"):
        return "LTE/WWAN"
    elif name.startswith("docker") or name.startswith("br-"):
        return "Docker"
    elif name.startswith("virbr"):
        return "Virtual"
    elif name == "lo":
        return "Loopback"
    else:
        return "Other"

def show_interfaces(interfaces):
    for line in interfaces.strip().splitlines():
        parts = line.split()

        if len(parts) >= 2:
            name = parts[0]
            state = parts[1]
            interface_type = get_interface_type(name)

            if name == "lo":
                status = "LOCAL"
            elif state == "UP":
                status = "ACTIVE"
            else:
                status = "INACTIVE"

            if len(parts) >= 3:
                address = parts[2]
            else:
                address = "-"

            print(interface_type, "|", name, "|", status, "|", address)

def get_connected_wifi():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "IN-USE,SSID", "dev", "wifi"],
            capture_output=True,
            text=True,
            check=True
        )

        for line in result.stdout.splitlines():
            if line.startswith("*:"):
                return line.split(":", 1)[1]

        return "Not connected"

    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Unavailable"

def get_wifi_networks():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,FREQ,SECURITY", "dev", "wifi", "list"],
            capture_output=True,
            text=True,
            check=True
        )

        networks = []

        for line in result.stdout.splitlines():
            parts = line.split(":", 3)

            if len(parts) == 4:
                ssid = parts[0] if parts[0] else "<Hidden>"
                signal = parts[1]
                frequency = parts[2]
                security = parts[3] if parts[3] else "Open"

                networks.append({
                    "ssid": ssid,
                    "signal": signal,
                    "frequency": frequency,
                    "security": security
                })

        return networks

    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

def show_wifi_networks(networks):
    print("\n=== Nearby Wi-Fi Networks ===")

    if not networks:
        print("No Wi-Fi networks found")
        return

    for network in networks:
        print(
            network["ssid"],
            "| Signal:", network["signal"] + "%",
            "| Freq:", network["frequency"] + " MHz",
            "| Security:", network["security"]
        )

hostname = socket.gethostname()
system = platform.system()
kernel = platform.release()
username = getpass.getuser()
architecture = platform.machine()
local_ip = get_local_ip()
interfaces = get_network_interfaces()
wifi_ssid = get_connected_wifi()
wifi_networks = get_wifi_networks()

print("=== Digital Footprint Radar v0.1 ===")
print("Hostname:", hostname)
print("System:", system)
print("Kernel:", kernel)
print("User:", username)
print("Architecture:", architecture)
print("Local IP:", local_ip)
print("Wi-Fi SSID:", wifi_ssid)

print("\n=== Network Interfaces ===")
show_interfaces(interfaces)
show_wifi_networks(wifi_networks)