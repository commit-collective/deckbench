# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small things about sockets that differ between systems."""
import socket
import sys
import json
import subprocess
import threading
import time
import ipaddress
import re


def parse_macos_interfaces(output):
    """Decode ifconfig records without assuming Ethernet names or one IPv4 per adapter."""
    records, current = [], None
    for line in output.splitlines():
        header = re.match(r"^(\S+): flags=[0-9a-fA-F]+<([^>]*)>", line)
        if header:
            current = {"name": header[1], "up": "UP" in header[2].split(","), "addresses": [], "mac": None}
            records.append(current)
        elif current is not None:
            fields = line.split()
            if fields[:1] == ["ether"] and len(fields) >= 2:
                if re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", fields[1]):
                    current["mac"] = bytes.fromhex(fields[1].replace(":", ""))
            elif fields[:1] == ["inet"] and "netmask" in fields:
                mask = fields[fields.index("netmask") + 1]
                if mask.startswith("0x"):
                    mask = str(ipaddress.IPv4Address(int(mask, 16)))
                current["addresses"].append(ipaddress.IPv4Interface("%s/%s" % (fields[1], mask)))
            elif fields == ["status:", "inactive"]:
                current["up"] = False
    return [(record["name"], address, record["mac"]) for record in records if record["up"]
            for address in record["addresses"]]


def macos_interfaces():
    """Read existing macOS interface addresses and link identities, without sudo or changes."""
    result = subprocess.run(["/sbin/ifconfig", "-a"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", timeout=10, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "interface listing failed")
    return parse_macos_interfaces(result.stdout)


class NetworkRuntime:
    """Own network workers and sockets so a bench can release its ports."""
    def __init__(self):
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.sockets = set()
        self.threads = []
        self.timers = []
        self.errors = []

    def own(self, sock):
        with self.lock:
            if self.stopping.is_set():
                sock.close()
                raise OSError("network runtime is stopped")
            self.sockets.add(sock)
        return sock

    def socket(self, *args):
        return self.own(socket.socket(*args))

    def release(self, sock):
        with self.lock:
            self.sockets.discard(sock)
        sock.close()

    def spawn(self, target, *args):
        def run():
            try:
                target(*args)
            except (OSError, ValueError) as error:
                if not self.stopping.is_set():
                    with self.lock:
                        self.errors.append("%s: %s" % (target.__name__, error))
        thread = threading.Thread(target=run, name="deckbench-" + target.__name__, daemon=True)
        with self.lock:
            if self.stopping.is_set():
                raise OSError("network runtime is stopped")
            self.threads = [worker for worker in self.threads if worker.is_alive()]
            self.threads.append(thread)
            thread.start()
        return thread

    def later(self, delay, target, *args):
        def call():
            if not self.stopping.is_set():
                target(*args)
        timer = threading.Timer(delay, call)
        timer.daemon = True
        with self.lock:
            if self.stopping.is_set():
                return
            self.timers = [worker for worker in self.timers if worker.is_alive()]
            self.timers.append(timer)
            timer.start()

    def close(self, timeout=2.0):
        self.stopping.set()
        with self.lock:
            sockets, threads, timers = list(self.sockets), list(self.threads), list(self.timers)
            self.sockets.clear()
        for timer in timers:
            timer.cancel()
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        deadline = time.monotonic() + timeout
        for thread in threads + timers:
            if thread is not threading.current_thread():
                thread.join(max(0, deadline - time.monotonic()))
        return not any(worker.is_alive() for worker in threads + timers)


def interface_macs():
    """IPv4 address to physical adapter MAC, without changing adapters."""
    if sys.platform == 'darwin':
        return {str(address.ip): mac for _, address, mac in macos_interfaces() if mac is not None}
    if sys.platform == 'win32':
        command = ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   'Get-NetIPConfiguration | ForEach-Object { '
                   'foreach ($ip in $_.IPv4Address) { '
                   '[pscustomobject]@{ip=$ip.IPAddress;mac=$_.NetAdapter.MacAddress} '
                   '} } | ConvertTo-Json -Compress']
    elif sys.platform.startswith('linux'):
        command = ['ip', '-j', 'address', 'show']           # not -4: it leaves the MAC out
    else:
        return {}
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=10, check=True)
    except subprocess.SubprocessError as error:
        raise ValueError('could not read network adapter information') from error
    data = json.loads(result.stdout or '[]')
    if sys.platform == 'win32':
        rows = data if isinstance(data, list) else [data]
        pairs = [(row['ip'], row['mac']) for row in rows if row.get('mac')]
    else:
        # WSL lists adapters without a link address (its mirrored loopback and tunnels): they have no MAC to give
        pairs = [(ip['local'], iface.get('address') or '') for iface in data
                 for ip in iface.get('addr_info', []) if ip.get('family') == 'inet']
    return {ip: bytes.fromhex(mac.replace(':', '').replace('-', ''))
            for ip, mac in pairs if len(mac.replace(':', '').replace('-', '')) == 12}


def share(sock):
    """Lets other sockets of this machine bind the same UDP port as this one: the decks, the sniffer and the mixer all listen on the
    link's ports. SO_REUSEADDR does it on Linux and Windows. macOS wants SO_REUSEPORT as well, and Linux must not get it here:
    there it would hand each datagram to one of the sockets instead of to all."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if sys.platform == "darwin" and hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    return sock
