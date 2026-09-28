import getpass
import ipaddress
import json
import platform
import re
import socket
import subprocess
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


# =========================================================
# CONFIG
# =========================================================

DATA_DIR = Path("data")
DEVICES_FILE = DATA_DIR / "devices.json"

MAX_WORKERS = 64

# Інтервал Live Radar у секундах
SCAN_INTERVAL = 5

KNOWN_DEVICES = {
    # "aa:bb:cc:dd:ee:ff": "My Phone",
}


# =========================================================
# HELPERS
# =========================================================

def run_command(command, timeout=5):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return result.stdout.strip()

    except (
        subprocess.SubprocessError,
        FileNotFoundError
    ):
        return ""


def now_string():
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def current_time():
    return datetime.now().strftime(
        "%H:%M:%S"
    )


def ensure_data_dir():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


# =========================================================
# SYSTEM
# =========================================================

def show_system_info():

    print(
        "\n=== DIGITAL FOOTPRINT RADAR ===\n"
    )

    print(
        "=== SYSTEM INFO ==="
    )

    print(
        f"Hostname:     {socket.gethostname()}"
    )

    print(
        f"System:       {platform.system()}"
    )

    print(
        f"Kernel:       {platform.release()}"
    )

    print(
        f"User:         {getpass.getuser()}"
    )

    print(
        f"Architecture: {platform.machine()}"
    )


# =========================================================
# NETWORK INTERFACES
# =========================================================

def get_interface_ipv4(interface):

    output = run_command(
        [
            "ip",
            "-o",
            "-4",
            "addr",
            "show",
            "dev",
            interface
        ]
    )

    for line in output.splitlines():

        parts = line.split()

        if "inet" in parts:

            index = parts.index("inet")

            return parts[index + 1]

    return None


def classify_interface(name):

    if name == "lo":
        return "Loopback"

    if name.startswith(
        ("wl", "wlan")
    ):
        return "Wi-Fi"

    if name.startswith(
        ("wwan", "wwp")
    ):
        return "LTE/WWAN"

    if name.startswith(
        ("en", "eth")
    ):
        return "Ethernet"

    if name.startswith(
        ("docker", "br-")
    ):
        return "Docker"

    if name.startswith(
        ("virbr", "vnet")
    ):
        return "Virtual"

    return "Other"


def show_network_interfaces():

    print(
        "\n=== NETWORK INTERFACES ===\n"
    )

    print(
        f"{'TYPE':<12}"
        f"{'INTERFACE':<16}"
        f"{'STATE':<12}"
        f"IPv4"
    )

    print("-" * 65)

    base = Path(
        "/sys/class/net"
    )

    if not base.exists():
        return

    for path in sorted(
        base.iterdir()
    ):

        name = path.name

        try:

            state = (
                (path / "operstate")
                .read_text()
                .strip()
                .upper()
            )

        except OSError:

            state = "UNKNOWN"

        ip = (
            get_interface_ipv4(name)
            or "-"
        )

        print(
            f"{classify_interface(name):<12}"
            f"{name:<16}"
            f"{state:<12}"
            f"{ip}"
        )


# =========================================================
# ACTIVE WI-FI
# =========================================================

def get_active_wifi_interface():

    output = run_command(
        [
            "nmcli",
            "-t",
            "-f",
            "DEVICE,TYPE,STATE",
            "device",
            "status"
        ]
    )

    for line in output.splitlines():

        parts = line.split(":")

        if len(parts) < 3:
            continue

        device = parts[0]
        device_type = parts[1]
        state = parts[2].lower()

        if (
            device_type == "wifi"
            and "connected" in state
        ):
            return device

    return None


def get_interface_ip_network(interface):

    address = get_interface_ipv4(
        interface
    )

    if not address:
        return None, None

    try:

        obj = ipaddress.ip_interface(
            address
        )

        return (
            str(obj.ip),
            obj.network
        )

    except ValueError:
        return None, None


def get_interface_mac(interface):

    path = Path(
        f"/sys/class/net/{interface}/address"
    )

    try:

        return (
            path
            .read_text()
            .strip()
            .lower()
        )

    except OSError:

        return "-"


def get_default_gateway():

    output = run_command(
        [
            "ip",
            "route",
            "show",
            "default"
        ]
    )

    match = re.search(
        r"default via ([0-9.]+)",
        output
    )

    if match:
        return match.group(1)

    return None


# =========================================================
# WI-FI SCANNER
# =========================================================

def split_nmcli_line(line):

    fields = []
    current = []
    escaped = False

    for char in line:

        if escaped:

            current.append(char)
            escaped = False

        elif char == "\\":

            escaped = True

        elif char == ":":

            fields.append(
                "".join(current)
            )

            current = []

        else:

            current.append(char)

    fields.append(
        "".join(current)
    )

    return fields


def clean_frequency(value):

    match = re.search(
        r"\d+",
        str(value)
    )

    if not match:
        return None

    return int(
        match.group()
    )


def get_band(freq):

    if freq is None:
        return "-"

    if 2400 <= freq <= 2500:
        return "2.4 GHz"

    if 4900 <= freq <= 5900:
        return "5 GHz"

    if 5925 <= freq <= 7125:
        return "6 GHz"

    return "Unknown"


def scan_wifi_networks(interface):

    output = run_command(
        [
            "nmcli",
            "-t",
            "-f",
            "IN-USE,SSID,SIGNAL,FREQ,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            interface,
            "--rescan",
            "yes"
        ],
        timeout=15
    )

    networks = []

    for line in output.splitlines():

        fields = split_nmcli_line(
            line
        )

        if len(fields) < 5:
            continue

        try:
            signal = int(fields[2])

        except ValueError:
            signal = 0

        frequency = clean_frequency(
            fields[3]
        )

        networks.append(
            {
                "current": fields[0] == "*",
                "ssid": (
                    fields[1]
                    or "<hidden>"
                ),
                "signal": signal,
                "frequency": frequency,
                "band": get_band(
                    frequency
                ),
                "security": (
                    fields[4]
                    or "Open"
                )
            }
        )

    return networks


def show_wifi(networks):

    print(
        "\n=== NEARBY WI-FI NETWORKS ===\n"
    )

    for network in networks:

        marker = (
            "*"
            if network["current"]
            else " "
        )

        frequency = (
            f"{network['frequency']} MHz"
            if network["frequency"]
            else "-"
        )

        print(
            f"{marker} "
            f"{network['ssid']} | "
            f"Signal: {network['signal']}% | "
            f"Freq: {frequency} | "
            f"Security: {network['security']}"
        )

    current = next(
        (
            net
            for net in networks
            if net["current"]
        ),
        None
    )

    print(
        "\n=== CURRENT WI-FI ==="
    )

    if current:

        print(
            f"SSID:      {current['ssid']}"
        )

        print(
            f"Signal:    {current['signal']}%"
        )

        print(
            f"Frequency: "
            f"{current['frequency']} MHz"
        )

        print(
            f"Band:      {current['band']}"
        )

        print(
            f"Security:  {current['security']}"
        )

    else:

        print(
            "Wi-Fi connection not found"
        )


# =========================================================
# DATABASE
# =========================================================

def load_devices():

    ensure_data_dir()

    if not DEVICES_FILE.exists():
        return {}

    try:

        with open(
            DEVICES_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

            if isinstance(data, dict):
                return data

    except (
        json.JSONDecodeError,
        OSError
    ):
        pass

    return {}


def save_devices(devices):

    ensure_data_dir()

    with open(
        DEVICES_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            devices,
            file,
            indent=4,
            ensure_ascii=False
        )


# =========================================================
# LAN DISCOVERY
# =========================================================

def ping_host(ip):

    try:

        result = subprocess.run(
            [
                "ping",
                "-c",
                "1",
                "-W",
                "1",
                str(ip)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2
        )

        return result.returncode == 0

    except subprocess.SubprocessError:

        return False


def get_neighbour_mac(ip):

    output = run_command(
        [
            "ip",
            "neigh",
            "show",
            str(ip)
        ]
    )

    match = re.search(
        r"lladdr\s+([0-9a-fA-F:]{17})",
        output
    )

    if match:

        return (
            match
            .group(1)
            .lower()
        )

    return "-"


def neighbour_alive(ip):

    output = run_command(
        [
            "ip",
            "neigh",
            "show",
            str(ip)
        ]
    )

    if not output:
        return False

    if (
        "FAILED" in output
        or "INCOMPLETE" in output
    ):
        return False

    return "lladdr" in output


def probe_host(ip):

    return (
        ping_host(ip)
        or neighbour_alive(ip)
    )


def find_online_hosts(
    network,
    local_ip
):

    hosts = list(
        network.hosts()
    )

    if len(hosts) > 1024:

        print(
            "[!] Network too large."
        )

        return []

    online = []

    workers = min(
        MAX_WORKERS,
        max(
            len(hosts),
            1
        )
    )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {}

        for ip in hosts:

            if str(ip) == local_ip:

                online.append(ip)
                continue

            future = executor.submit(
                probe_host,
                ip
            )

            futures[future] = ip

        for future in as_completed(
            futures
        ):

            ip = futures[future]

            try:

                if future.result():
                    online.append(ip)

            except Exception:
                pass

    return sorted(
        online,
        key=int
    )


def get_hostname(ip):

    try:

        result = subprocess.run(
            [
                "getent",
                "hosts",
                str(ip)
            ],
            capture_output=True,
            text=True,
            timeout=1
        )

        parts = (
            result.stdout
            .strip()
            .split()
        )

        if len(parts) >= 2:
            return parts[1]

    except subprocess.SubprocessError:
        pass

    return "-"


# =========================================================
# VENDOR
# =========================================================

OUI_DATABASE = None


def normalize_oui(value):

    return re.sub(
        r"[^0-9A-Fa-f]",
        "",
        value
    ).upper()[:6]


def load_oui_database():

    global OUI_DATABASE

    if OUI_DATABASE is not None:
        return OUI_DATABASE

    database = {}

    files = [
        Path("/usr/share/wireshark/manuf"),
        Path("/usr/share/hwdata/oui.txt"),
        Path("/usr/share/ieee-data/oui.txt"),
    ]

    for path in files:

        if not path.exists():
            continue

        try:

            with open(
                path,
                "r",
                encoding="utf-8",
                errors="ignore"
            ) as file:

                for raw_line in file:

                    line = raw_line.strip()

                    if (
                        not line
                        or line.startswith("#")
                    ):
                        continue

                    if "\t" in line:

                        parts = line.split()

                        if len(parts) >= 2:

                            oui = normalize_oui(
                                parts[0]
                            )

                            if len(oui) == 6:

                                database.setdefault(
                                    oui,
                                    " ".join(
                                        parts[1:]
                                    )[:60]
                                )

                    elif "(hex)" in line:

                        before, after = (
                            line.split(
                                "(hex)",
                                1
                            )
                        )

                        oui = normalize_oui(
                            before
                        )

                        vendor = after.strip()

                        if (
                            len(oui) == 6
                            and vendor
                        ):

                            database.setdefault(
                                oui,
                                vendor[:60]
                            )

        except OSError:
            continue

    OUI_DATABASE = database

    return database


def get_vendor(mac):

    if (
        not mac
        or mac == "-"
    ):
        return "-"

    return (
        load_oui_database()
        .get(
            normalize_oui(mac),
            "Unknown"
        )
    )


# =========================================================
# DEVICE IDENTITY
# =========================================================

def get_device_id(device):

    mac = device.get(
        "mac",
        "-"
    )

    if (
        mac
        and mac != "-"
    ):
        return mac.lower()

    return (
        "ip:"
        + device["ip"]
    )


def identify_device(
    device,
    local_ip,
    gateway_ip
):

    if device["ip"] == local_ip:

        return (
            True,
            "My Laptop"
        )

    if (
        gateway_ip
        and device["ip"]
        == gateway_ip
    ):

        return (
            True,
            "Gateway"
        )

    mac = device["mac"]

    if (
        mac != "-"
        and mac.lower()
        in KNOWN_DEVICES
    ):

        return (
            True,
            KNOWN_DEVICES[
                mac.lower()
            ]
        )

    return (
        False,
        "-"
    )


# =========================================================
# HISTORY
# =========================================================

def update_history(
    devices,
    local_ip,
    gateway_ip
):

    history = load_devices()

    timestamp = now_string()

    current_ids = set()

    for device in devices:

        device_id = (
            get_device_id(
                device
            )
        )

        current_ids.add(
            device_id
        )

        known, name = (
            identify_device(
                device,
                local_ip,
                gateway_ip
            )
        )

        existing = (
            device_id in history
        )

        if not existing:

            history[device_id] = {
                "ip": device["ip"],
                "mac": device["mac"],
                "hostname": (
                    device["hostname"]
                ),
                "vendor": (
                    device["vendor"]
                ),
                "name": name,
                "known": known,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "status": "ONLINE"
            }

            device["new"] = True

        else:

            saved = history[
                device_id
            ]

            saved["ip"] = (
                device["ip"]
            )

            saved["mac"] = (
                device["mac"]
            )

            saved["hostname"] = (
                device["hostname"]
            )

            saved["vendor"] = (
                device["vendor"]
            )

            saved["last_seen"] = (
                timestamp
            )

            saved["status"] = (
                "ONLINE"
            )

            if known:

                saved["known"] = True
                saved["name"] = name

            device["new"] = False

        saved = history[
            device_id
        ]

        device["known"] = (
            saved.get(
                "known",
                False
            )
        )

        device["name"] = (
            saved.get(
                "name",
                "-"
            )
        )

        device["first_seen"] = (
            saved.get(
                "first_seen",
                timestamp
            )
        )

        device["last_seen"] = (
            saved.get(
                "last_seen",
                timestamp
            )
        )

    for device_id, saved in (
        history.items()
    ):

        if (
            device_id
            not in current_ids
        ):

            saved["status"] = (
                "OFFLINE"
            )

    save_devices(
        history
    )

    return history


# =========================================================
# LAN SNAPSHOT
# =========================================================

def scan_lan_snapshot(
    interface,
    quiet=False
):

    local_ip, network = (
        get_interface_ip_network(
            interface
        )
    )

    if (
        not local_ip
        or network is None
    ):

        return (
            [],
            {},
            None,
            None,
            None
        )

    local_mac = (
        get_interface_mac(
            interface
        )
    )

    gateway_ip = (
        get_default_gateway()
    )

    if not quiet:

        print(
            "\n=== LAN SCANNER ==="
        )

        print(
            f"Interface: {interface}"
        )

        print(
            f"Local IP:  {local_ip}"
        )

        print(
            f"Local MAC: {local_mac}"
        )

        print(
            f"Gateway:   "
            f"{gateway_ip or '-'}"
        )

        print(
            f"Network:   {network}"
        )

        print(
            "\nScanning..."
        )

    online_hosts = (
        find_online_hosts(
            network,
            local_ip
        )
    )

    devices = []

    for ip in online_hosts:

        ip_text = str(ip)

        if ip_text == local_ip:

            mac = local_mac

            hostname = (
                socket.gethostname()
            )

        else:

            mac = (
                get_neighbour_mac(
                    ip
                )
            )

            hostname = (
                get_hostname(ip)
            )

        devices.append(
            {
                "ip": ip_text,
                "mac": mac,
                "hostname": hostname,
                "vendor": (
                    get_vendor(mac)
                )
            }
        )

    history = update_history(
        devices,
        local_ip,
        gateway_ip
    )

    return (
        devices,
        history,
        local_ip,
        gateway_ip,
        network
    )


# =========================================================
# OUTPUT
# =========================================================

def device_type(device):

    if device.get("known"):
        return "KNOWN"

    if device.get("new"):
        return "NEW"

    return "UNKNOWN"


def show_devices(devices):

    print(
        "\n=== ONLINE DEVICES ===\n"
    )

    print(
        f"{'IP':<16}"
        f"{'MAC':<20}"
        f"{'HOSTNAME':<18}"
        f"{'NAME':<16}"
        f"{'TYPE':<10}"
        f"STATUS"
    )

    print(
        "-" * 100
    )

    for device in devices:

        print(
            f"{device['ip']:<16}"
            f"{device['mac']:<20}"
            f"{device['hostname']:<18}"
            f"{device.get('name', '-'):<16}"
            f"{device_type(device):<10}"
            f"ONLINE"
        )

    print(
        f"\nOnline devices: "
        f"{len(devices)}"
    )


def show_history(history):

    print(
        "\n=== DEVICE HISTORY ===\n"
    )

    print(
        f"{'IP':<16}"
        f"{'NAME':<16}"
        f"{'HOSTNAME':<18}"
        f"{'TYPE':<10}"
        f"{'STATUS':<10}"
        f"LAST SEEN"
    )

    print(
        "-" * 105
    )

    for device in history.values():

        dtype = (
            "KNOWN"
            if device.get(
                "known"
            )
            else "UNKNOWN"
        )

        print(
            f"{device.get('ip', '-'):<16}"
            f"{device.get('name', '-'):<16}"
            f"{device.get('hostname', '-'):<18}"
            f"{dtype:<10}"
            f"{device.get('status', '-'):<10}"
            f"{device.get('last_seen', '-')}"
        )


# =========================================================
# LIVE RADAR EVENTS
# =========================================================

def devices_to_map(devices):

    return {
        get_device_id(device): device
        for device in devices
    }


def show_join_event(device):

    print(
        "\n"
        "========================================"
    )

    print(
        f"[+] DEVICE JOINED  {current_time()}"
    )

    print(
        "========================================"
    )

    print(
        f"IP:       {device['ip']}"
    )

    print(
        f"MAC:      {device['mac']}"
    )

    print(
        f"Hostname: {device['hostname']}"
    )

    print(
        f"Vendor:   {device['vendor']}"
    )

    print(
        f"Name:     "
        f"{device.get('name', '-')}"
    )

    print(
        f"Type:     "
        f"{device_type(device)}"
    )

    if (
        device.get("new")
        and not device.get("known")
    ):

        print(
            "\n[!] NEW UNKNOWN DEVICE"
        )


def show_leave_event(device):

    print(
        "\n"
        "========================================"
    )

    print(
        f"[-] DEVICE LEFT  {current_time()}"
    )

    print(
        "========================================"
    )

    print(
        f"IP:       {device['ip']}"
    )

    print(
        f"MAC:      {device['mac']}"
    )

    print(
        f"Hostname: {device['hostname']}"
    )

    print(
        f"Name:     "
        f"{device.get('name', '-')}"
    )


# =========================================================
# LIVE RADAR
# =========================================================

def live_radar(
    interface,
    initial_devices
):

    previous = (
        devices_to_map(
            initial_devices
        )
    )

    print(
        "\n=== LIVE RADAR ==="
    )

    print(
        f"Scan interval: "
        f"{SCAN_INTERVAL} seconds"
    )

    print(
        "Watching for devices..."
    )

    print(
        "Press Ctrl+C to stop.\n"
    )

    try:

        while True:

            time.sleep(
                SCAN_INTERVAL
            )

            (
                current_devices,
                _,
                _,
                _,
                _
            ) = scan_lan_snapshot(
                interface,
                quiet=True
            )

            current = (
                devices_to_map(
                    current_devices
                )
            )

            joined = (
                current.keys()
                - previous.keys()
            )

            left = (
                previous.keys()
                - current.keys()
            )

            for device_id in joined:

                show_join_event(
                    current[
                        device_id
                    ]
                )

            for device_id in left:

                show_leave_event(
                    previous[
                        device_id
                    ]
                )

            previous = current

    except KeyboardInterrupt:

        print(
            "\n\n=== LIVE RADAR STOPPED ==="
        )


# =========================================================
# MAIN
# =========================================================

def main():

    show_system_info()

    show_network_interfaces()

    interface = (
        get_active_wifi_interface()
    )

    if not interface:

        print(
            "\n[!] Active Wi-Fi "
            "interface not found."
        )

        return

    local_ip, _ = (
        get_interface_ip_network(
            interface
        )
    )

    print(
        f"\nActive Wi-Fi interface: "
        f"{interface}"
    )

    print(
        f"Local IP: "
        f"{local_ip or '-'}"
    )

    networks = (
        scan_wifi_networks(
            interface
        )
    )

    show_wifi(
        networks
    )

    (
        devices,
        history,
        _,
        _,
        _
    ) = scan_lan_snapshot(
        interface
    )

    show_devices(
        devices
    )

    show_history(
        history
    )

    print(
        f"\nDatabase: "
        f"{DEVICES_FILE}"
    )

    live_radar(
        interface,
        devices
    )


if __name__ == "__main__":
    main()