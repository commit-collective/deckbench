# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small things about sockets that differ between systems."""
import socket
import sys
import json
import subprocess
import threading
import time


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
    if sys.platform == 'win32':
        command = ['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   'Get-NetIPConfiguration | ForEach-Object { '
                   'foreach ($ip in $_.IPv4Address) { '
                   '[pscustomobject]@{ip=$ip.IPAddress;mac=$_.NetAdapter.MacAddress} '
                   '} } | ConvertTo-Json -Compress']
    elif sys.platform.startswith('linux'):
        command = ['ip', '-j', '-4', 'address', 'show']
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
        pairs = [(ip['local'], iface['address']) for iface in data
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
