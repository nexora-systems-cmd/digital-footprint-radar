import getpass
import ipaddress
import json
import platform
import re
import socket
import subprocess

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


# =========================================================
# CONFIG
# =========================================================

DATA_DIR = Path("data")
DEVICES_FILE = DATA_DIR / "devices.json"

MAX_WORKERS = 64

# Сюди пізніше можна додавати свої пристрої вручну:
#
# KNOWN_DEVICES = {
#     "aa:bb:cc:dd:ee:ff": "My Phone",
# }
#
KNOWN_DEVICES = {}


# =========================================================
# GENERAL HELPERS
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


def ensure_data_dir():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


# =========================================================
# SYSTEM INFO
# =========================================================

def get_system_info():

    hostname = socket.gethostname()
    system = platform.system()
    kernel = platform.release()
    user = getpass.getuser()
    architecture = platform.machine()

    return {
        "hostname": hostname,
        "system": system,
        "kernel": kernel,
        "user": user,
        "architecture": architecture,
    }


def show_system_info():

    info = get_system_info()

    print(
        "\n=== DIGITAL FOOTPRINT RADAR ===\n"
    )

    print(
        "=== SYSTEM INFO ==="
    )

    print(
        f"Hostname:     {info['hostname']}"
    )

    print(
        f"System:       {info['system']}"
    )

    print(
        f"Kernel:       {info['kernel']}"
    )

    print(
        f"User:         {info['user']}"
    )

    print(
        f"Architecture: {info['architecture']}"
    )


# =========================================================
# NETWORK INTERFACE DETECTION
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

    # Fallback
    output = run_command(
        [
            "iw",
            "dev"
        ]
    )

    match = re.search(
        r"Interface\s+(\S+)",
        output
    )

    if match:
        return match.group(1)

    return None


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


def get_interface_ip_and_network(interface):

    address = get_interface_ipv4(
        interface
    )

    if not address:
        return None, None

    try:

        interface_object = (
            ipaddress.ip_interface(
                address
            )
        )

        return (
            str(interface_object.ip),
            interface_object.network
        )

    except ValueError:
        return None, None


def get_interface_mac(interface):

    path = Path(
        f"/sys/class/net/{interface}/address"
    )

    try:

        return (
            path.read_text()
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
# NETWORK INTERFACES
# =========================================================

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


def get_network_interfaces():

    base = Path(
        "/sys/class/net"
    )

    interfaces = []

    if not base.exists():
        return interfaces

    for interface_path in sorted(
        base.iterdir()
    ):

        name = interface_path.name

        state_path = (
            interface_path / "operstate"
        )

        try:

            state = (
                state_path
                .read_text()
                .strip()
                .upper()
            )

        except OSError:

            state = "UNKNOWN"

        ipv4 = get_interface_ipv4(
            name
        )

        interfaces.append(
            {
                "name": name,
                "type": classify_interface(
                    name
                ),
                "state": state,
                "ip": ipv4 or "-"
            }
        )

    return interfaces


def show_network_interfaces():

    interfaces = (
        get_network_interfaces()
    )

    print(
        "\n=== NETWORK INTERFACES ===\n"
    )

    print(
        f"{'TYPE':<12}"
        f"{'INTERFACE':<16}"
        f"{'STATE':<12}"
        f"{'IPv4'}"
    )

    print(
        "-" * 65
    )

    for interface in interfaces:

        print(
            f"{interface['type']:<12}"
            f"{interface['name']:<16}"
            f"{interface['state']:<12}"
            f"{interface['ip']}"
        )


# =========================================================
# WI-FI
# =========================================================

def split_nmcli_line(line):
    """
    nmcli -t екранує ':' як '\\:'.
    Ця функція правильно розбиває поля.
    """

    result = []
    current = []
    escaped = False

    for char in line:

        if escaped:

            current.append(char)
            escaped = False

        elif char == "\\":

            escaped = True

        elif char == ":":

            result.append(
                "".join(current)
            )

            current = []

        else:

            current.append(char)

    result.append(
        "".join(current)
    )

    return result


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


def get_band(frequency):

    if frequency is None:
        return "-"

    if 2400 <= frequency <= 2500:
        return "2.4 GHz"

    if 4900 <= frequency <= 5900:
        return "5 GHz"

    if 5925 <= frequency <= 7125:
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

        in_use = fields[0]
        ssid = fields[1] or "<hidden>"

        try:
            signal = int(fields[2])
        except ValueError:
            signal = 0

        frequency = clean_frequency(
            fields[3]
        )

        security = (
            fields[4]
            if fields[4]
            else "Open"
        )

        networks.append(
            {
                "current": in_use == "*",
                "ssid": ssid,
                "signal": signal,
                "frequency": frequency,
                "band": get_band(
                    frequency
                ),
                "security": security,
            }
        )

    return networks


def show_wifi_networks(networks):

    print(
        "\n=== NEARBY WI-FI NETWORKS ===\n"
    )

    if not networks:

        print(
            "No Wi-Fi networks found."
        )

        return

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


def show_current_wifi(networks):

    current = next(
        (
            network
            for network in networks
            if network["current"]
        ),
        None
    )

    print(
        "\n=== CURRENT WI-FI ==="
    )

    if not current:

        print(
            "Wi-Fi connection not found"
        )

        return

    print(
        f"SSID:      {current['ssid']}"
    )

    print(
        f"Signal:    {current['signal']}%"
    )

    print(
        f"Frequency: {current['frequency']} MHz"
    )

    print(
        f"Band:      {current['band']}"
    )

    print(
        f"Security:  {current['security']}"
    )


# =========================================================
# DEVICE DATABASE
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

        return (
            result.returncode == 0
        )

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


def neighbour_is_alive(ip):

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

    ping_success = ping_host(
        ip
    )

    neighbour_success = (
        neighbour_is_alive(
            ip
        )
    )

    return (
        ping_success
        or neighbour_success
    )


def find_online_hosts(
    network,
    local_ip
):

    hosts = list(
        network.hosts()
    )

    # Не даємо випадково запустити
    # величезний скан.
    if len(hosts) > 1024:

        print(
            "[!] Network is too large "
            "for the current scanner."
        )

        return []

    online_hosts = []

    workers = min(
        MAX_WORKERS,
        max(
            1,
            len(hosts)
        )
    )

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {}

        for ip in hosts:

            # Свій комп'ютер не треба ping-ати
            if str(ip) == local_ip:

                online_hosts.append(
                    ip
                )

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

                    online_hosts.append(
                        ip
                    )

            except Exception:
                pass

    return sorted(
        online_hosts,
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

        output = (
            result.stdout
            .strip()
        )

        if output:

            parts = output.split()

            if len(parts) >= 2:
                return parts[1]

    except subprocess.SubprocessError:
        pass

    return "-"


# =========================================================
# MAC VENDOR DATABASE
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
        Path(
            "/usr/share/wireshark/manuf"
        ),
        Path(
            "/usr/share/hwdata/oui.txt"
        ),
        Path(
            "/usr/share/ieee-data/oui.txt"
        ),
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

                    # Wireshark manuf format
                    if "\t" in line:

                        parts = (
                            line.split()
                        )

                        if len(parts) >= 2:

                            prefix = (
                                parts[0]
                                .split("/")[0]
                            )

                            oui = normalize_oui(
                                prefix
                            )

                            if len(oui) == 6:

                                database.setdefault(
                                    oui,
                                    " ".join(
                                        parts[1:]
                                    )[:60]
                                )

                    # IEEE / hwdata format
                    if "(hex)" in line:

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

    oui = normalize_oui(
        mac
    )

    database = (
        load_oui_database()
    )

    return database.get(
        oui,
        "Unknown"
    )


# =========================================================
# DEVICE IDENTITY
# =========================================================

def get_device_id(ip, mac):

    if (
        mac
        and mac != "-"
    ):
        return mac.lower()

    return f"ip:{ip}"


def identify_known_device(
    device,
    local_ip,
    gateway_ip
):

    mac = device["mac"]

    # Наш ноутбук
    if device["ip"] == local_ip:

        return True, "My Laptop"

    # Поточний gateway/router
    if (
        gateway_ip
        and device["ip"] == gateway_ip
    ):

        return True, "Gateway"

    # Ручний список
    if (
        mac
        and mac != "-"
        and mac.lower()
        in KNOWN_DEVICES
    ):

        return (
            True,
            KNOWN_DEVICES[
                mac.lower()
            ]
        )

    return False, "-"


# =========================================================
# HISTORY MIGRATION / CLEANUP
# =========================================================

def merge_first_seen(
    first,
    second
):

    values = [
        value
        for value in (
            first,
            second
        )
        if value
    ]

    if not values:
        return now_string()

    return min(values)


def cleanup_duplicate_history(
    history
):

    mac_records_by_ip = {}

    for device_id, device in history.items():

        if device_id.startswith(
            "ip:"
        ):
            continue

        ip = device.get("ip")

        if ip:
            mac_records_by_ip[ip] = (
                device_id
            )

    remove_ids = []

    for device_id, device in history.items():

        if not device_id.startswith(
            "ip:"
        ):
            continue

        ip = device.get("ip")

        if (
            ip
            and ip in mac_records_by_ip
        ):

            mac_id = (
                mac_records_by_ip[ip]
            )

            mac_record = (
                history[mac_id]
            )

            mac_record["first_seen"] = (
                merge_first_seen(
                    mac_record.get(
                        "first_seen"
                    ),
                    device.get(
                        "first_seen"
                    )
                )
            )

            remove_ids.append(
                device_id
            )

    for device_id in remove_ids:

        history.pop(
            device_id,
            None
        )

    return history


# =========================================================
# HISTORY UPDATE
# =========================================================

def update_history(
    current_devices,
    local_ip,
    gateway_ip
):

    history = load_devices()

    history = (
        cleanup_duplicate_history(
            history
        )
    )

    current_ids = set()

    timestamp = now_string()

    for device in current_devices:

        ip = device["ip"]
        mac = device["mac"]

        device_id = get_device_id(
            ip,
            mac
        )

        legacy_id = f"ip:{ip}"

        migrated = False

        # Старий запис без MAC -> новий MAC ID
        if (
            mac != "-"
            and legacy_id in history
            and legacy_id != device_id
        ):

            legacy_record = (
                history.pop(
                    legacy_id
                )
            )

            if device_id in history:

                history[device_id][
                    "first_seen"
                ] = merge_first_seen(
                    history[
                        device_id
                    ].get(
                        "first_seen"
                    ),
                    legacy_record.get(
                        "first_seen"
                    )
                )

            else:

                history[device_id] = (
                    legacy_record
                )

            migrated = True

        current_ids.add(
            device_id
        )

        known, name = (
            identify_known_device(
                device,
                local_ip,
                gateway_ip
            )
        )

        existed_before = (
            device_id in history
        )

        if not existed_before:

            history[device_id] = {
                "ip": ip,
                "mac": mac,
                "hostname": (
                    device["hostname"]
                ),
                "vendor": (
                    device["vendor"]
                ),
                "name": name,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "status": "ONLINE",
                "known": known,
            }

            new_device = True

        else:

            saved = (
                history[device_id]
            )

            saved["ip"] = ip
            saved["mac"] = mac

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

            else:

                saved.setdefault(
                    "known",
                    False
                )

                saved.setdefault(
                    "name",
                    "-"
                )

            new_device = False

        # Міграція старого запису не є
        # появою нового пристрою.
        if migrated:
            new_device = False

        saved = history[
            device_id
        ]

        device["new"] = (
            new_device
        )

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

    # Все, чого зараз немає, OFFLINE
    for (
        device_id,
        saved
    ) in history.items():

        if (
            device_id
            not in current_ids
        ):

            saved["status"] = (
                "OFFLINE"
            )

    history = (
        cleanup_duplicate_history(
            history
        )
    )

    save_devices(
        history
    )

    return (
        current_devices,
        history
    )


# =========================================================
# DISPLAY
# =========================================================

def get_device_type(device):

    if device.get(
        "known"
    ):
        return "KNOWN"

    if device.get(
        "new"
    ):
        return "NEW"

    return "UNKNOWN"


def show_devices(devices):

    print(
        "\n=== ONLINE DEVICES ===\n"
    )

    if not devices:

        print(
            "No devices found."
        )

        return

    print(
        f"{'IP':<16}"
        f"{'MAC':<20}"
        f"{'HOSTNAME':<18}"
        f"{'NAME':<16}"
        f"{'TYPE':<10}"
        f"{'STATUS'}"
    )

    print(
        "-" * 100
    )

    for device in devices:

        print(
            f"{device['ip']:<16}"
            f"{device['mac']:<20}"
            f"{device['hostname']:<18}"
            f"{device['name']:<16}"
            f"{get_device_type(device):<10}"
            f"ONLINE"
        )


def show_new_device_alerts(
    devices
):

    unknown_new_devices = [
        device
        for device in devices
        if (
            device.get("new")
            and not device.get(
                "known"
            )
        )
    ]

    if not unknown_new_devices:
        return

    print(
        "\n=== NEW DEVICE ALERTS ==="
    )

    for device in (
        unknown_new_devices
    ):

        print(
            "\n[NEW UNKNOWN DEVICE]"
        )

        print(
            f"IP:         {device['ip']}"
        )

        print(
            f"MAC:        {device['mac']}"
        )

        print(
            f"Hostname:   {device['hostname']}"
        )

        print(
            f"Vendor:     {device['vendor']}"
        )

        print(
            f"First seen: {device['first_seen']}"
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
        f"{'LAST SEEN'}"
    )

    print(
        "-" * 105
    )

    def sort_key(item):

        device = item[1]

        try:

            return int(
                ipaddress.ip_address(
                    device.get(
                        "ip",
                        "255.255.255.255"
                    )
                )
            )

        except ValueError:
            return 999999999999

    for (
        _,
        device
    ) in sorted(
        history.items(),
        key=sort_key
    ):

        device_type = (
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
            f"{device_type:<10}"
            f"{device.get('status', '-'):<10}"
            f"{device.get('last_seen', '-')}"
        )


# =========================================================
# LAN SCANNER
# =========================================================

def scan_lan(interface):

    local_ip, network = (
        get_interface_ip_and_network(
            interface
        )
    )

    local_mac = (
        get_interface_mac(
            interface
        )
    )

    gateway_ip = (
        get_default_gateway()
    )

    print(
        "\n=== LAN SCANNER ==="
    )

    if (
        not local_ip
        or network is None
    ):

        print(
            "[!] Active IPv4 network "
            "not found."
        )

        return []

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
        f"Gateway:   {gateway_ip or '-'}"
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

        ip_string = str(ip)

        if ip_string == local_ip:

            mac = local_mac

        else:

            mac = (
                get_neighbour_mac(
                    ip
                )
            )

        hostname = get_hostname(
            ip
        )

        # Для нашого ПК гарантуємо
        # нормальне ім'я.
        if ip_string == local_ip:

            hostname = (
                socket.gethostname()
            )

        vendor = get_vendor(
            mac
        )

        devices.append(
            {
                "ip": ip_string,
                "mac": mac,
                "hostname": hostname,
                "vendor": vendor,
            }
        )

    devices, history = (
        update_history(
            devices,
            local_ip,
            gateway_ip
        )
    )

    show_devices(
        devices
    )

    print(
        f"\nOnline devices: "
        f"{len(devices)}"
    )

    show_new_device_alerts(
        devices
    )

    show_history(
        history
    )

    print(
        f"\nDatabase: "
        f"{DEVICES_FILE}"
    )

    return devices


# =========================================================
# MAIN
# =========================================================

def main():

    show_system_info()

    show_network_interfaces()

    wifi_interface = (
        get_active_wifi_interface()
    )

    if not wifi_interface:

        print(
            "\n[!] Active Wi-Fi "
            "interface not found."
        )

        return

    local_ip, _ = (
        get_interface_ip_and_network(
            wifi_interface
        )
    )

    print(
        f"\nActive Wi-Fi interface: "
        f"{wifi_interface}"
    )

    print(
        f"Local IP: "
        f"{local_ip or '-'}"
    )

    wifi_networks = (
        scan_wifi_networks(
            wifi_interface
        )
    )

    show_wifi_networks(
        wifi_networks
    )

    show_current_wifi(
        wifi_networks
    )

    scan_lan(
        wifi_interface
    )


if __name__ == "__main__":
    main()