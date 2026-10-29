# SPDX-License-Identifier: MIT OR Apache-2.0
"""Local phone pairing without sending connection details to a third party."""
import ipaddress
import json
import socket
import subprocess
import sys
from urllib.parse import urlencode


SITE = "https://commitcollective.cc"
APP = SITE + "/deckbench/app/"


def interfaces():
    """Return preferred IPv4 interfaces without changing the network."""
    if sys.platform == "win32":
        command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   "Get-NetIPAddress -AddressFamily IPv4 | "
                   "Where-Object { $_.AddressState -eq 'Preferred' } | "
                   "Select-Object InterfaceAlias,IPAddress,PrefixLength | ConvertTo-Json -Compress"]
    elif sys.platform.startswith("linux"):
        command = ["ip", "-j", "-4", "address", "show"]
    else:
        raise ValueError("interface selection is supported on Windows and Linux")
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", timeout=10, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "interface listing failed")
    data = json.loads(result.stdout or "[]")
    if sys.platform == "win32":
        entries = data if isinstance(data, list) else [data]
        entries = [(x["InterfaceAlias"], x["IPAddress"], x["PrefixLength"]) for x in entries]
    else:
        entries = [(iface["ifname"], a["local"], a["prefixlen"]) for iface in data
                   for a in iface.get("addr_info", []) if a.get("family") == "inet"]
    return [(name, ipaddress.IPv4Interface("%s/%s" % (address, prefix))) for name, address, prefix in entries]


def dj_interface(name, count):
    """Select already configured addresses, refusing missing or ambiguous networks."""
    if count < 1:
        raise ValueError("at least one deck is required")
    found = list(dict.fromkeys(ip for alias, ip in interfaces() if alias == name and not ip.ip.is_loopback))
    if not found:
        raise ValueError("no preferred IPv4 address on interface %s" % name)
    if len({ip.network for ip in found}) != 1:
        raise ValueError("interface %s has multiple subnets, use --bind and --netmask explicitly" % name)
    if len({ip.ip for ip in found}) < count:
        raise ValueError("interface %s has %d IPv4 addresses but %d decks need one each" % (name, len(found), count))
    return found[:count]


def network_info(out):
    """Show OS interface information without changing the network."""
    try:
        entries = interfaces()
        route = route_address()
        out.write("IPv4 interfaces (read-only):\n")
        for name, iface in entries:
            if iface.ip.is_loopback:
                continue
            out.write("  %s: %s/%s, mask %s%s\n" %
                      (name, iface.ip, iface.network.prefixlen, iface.netmask,
                       " (default route candidate)" if str(iface.ip) == route else ""))
        out.write("Choose the DJ adapter separately from the address reachable by the phone.\n")
        out.write("One deck can use the DJ adapter's existing address with --bind ADDRESS --netmask MASK.\n")
        out.write("Multiple decks need separate unused addresses. See docs/real-network.md.\n")
        return 0
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        out.write("Cannot list network interfaces: %s\n" % exc)
        return 1


def route_address():
    """Ask the OS which local IPv4 address it would use for the default route.

    UDP connect selects a route without transmitting a packet. The result is a
    candidate, not proof that the phone can reach it.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
    except OSError:
        return None


def pairing_url(address, port, token):
    ip = ipaddress.IPv4Address(address)
    if ip.is_unspecified or ip.is_loopback or ip.is_multicast:
        raise ValueError("the phone needs a reachable non-loopback IPv4 address")
    if not 1 <= port <= 65535 or not token:
        raise ValueError("a listening port and token are required")
    return APP + "#" + urlencode({"bench": "http://%s:%d" % (ip, port), "token": token})


def print_qr(url, out):
    """Print a QR locally when the optional qrcode package is installed."""
    try:
        import qrcode
    except ImportError:
        return False
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    try:
        qr.print_ascii(out=out, invert=True)
        return True
    except UnicodeEncodeError:
        return False
