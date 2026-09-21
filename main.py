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

hostname = socket.gethostname()
system = platform.system()
kernel = platform.release()
username = getpass.getuser()
architecture = platform.machine()
local_ip = get_local_ip()
interfaces = get_network_interfaces()

print("=== Digital Footprint Radar v0.1 ===")
print("Hostname:", hostname)
print("System:", system)
print("Kernel:", kernel)
print("User:", username)
print("Architecture:", architecture)
print("Local IP:", local_ip)
print("\n=== Network Interfaces ===")
print(interfaces)
