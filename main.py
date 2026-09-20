import socket
import platform

hostname = socket.gethostname()
system = platform.system()
kernel = platform.release()

print("=== Digital Footprint Radar v0.1 ===")
print("Hostname:", hostname)
print("System:", system)
print("Kernel:", kernel)