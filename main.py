import socket
import platform
import getpass

hostname = socket.gethostname()
system = platform.system()
kernel = platform.release()
username = getpass.getuser()
architecture = platform.machine()

print("=== Digital Footprint Radar v0.1 ===")
print("Hostname:", hostname)
print("System:", system)
print("Kernel:", kernel)
print("User:", username)
print("Architecture:", architecture)