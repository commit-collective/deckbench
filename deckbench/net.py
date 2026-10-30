# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small things about sockets that differ between systems."""
import socket
import sys
import json
import subprocess


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
