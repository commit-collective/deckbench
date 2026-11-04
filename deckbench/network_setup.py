# SPDX-License-Identifier: MIT OR Apache-2.0
"""Read-only adapter discovery and explicit reconnection of an idle bench."""
import ipaddress
import json
import os
import subprocess
import tempfile

from . import phone
from .net import interface_macs


class NetworkSetup:
    def __init__(self, link, interface=None, settings=None, netmask='255.255.255.0'):
        self.link = link
        self.interface = interface
        self.settings = settings or os.path.expanduser('~/.deckbench/network.json')
        address = next(iter(link.decks.values())).address
        if interface:
            link.source_network = ipaddress.IPv4Interface(address + '/' + netmask).network

    def current(self):
        return {'interface': self.interface or '',
                'addresses': {str(n): d.address for n, d in self.link.decks.items()},
                'broadcast': next(iter(self.link.decks.values())).broadcast,
                'subnet': str(self.link.source_network) if self.link.source_network else None}

    def snapshot(self):
        """The interfaces belong to the server, never to the browser's device."""
        interfaces, error = {}, ''
        try:
            route = phone.route_address()
            for name, ip in phone.interfaces():
                if ip.ip.is_loopback:
                    continue
                row = interfaces.setdefault(name, {'name': name, 'addresses': [], 'default_route': False})
                row['addresses'].append(str(ip))
                row['default_route'] |= str(ip.ip) == route
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
            error = 'Could not list adapters: %s' % exc
        remembered = ''
        try:
            with open(self.settings, encoding='utf-8') as source:
                remembered = json.load(source).get('interface', '')
            if not isinstance(remembered, str):
                remembered = ''
        except (OSError, ValueError, AttributeError):
            pass
        return {'current': self.current(), 'interfaces': list(interfaces.values()),
                'remembered': remembered, 'error': error,
                'endpoints': len(self.link.decks)}

    def apply(self, name, remember=False):
        if not isinstance(name, str) or len(name) > 256 or not isinstance(remember, bool):
            raise ValueError('interface must be a name, and remember must be true or false')
        link = self.link
        if name:
            try:
                selected = phone.dj_interface(name, len(link.decks))
                macs = interface_macs()
            except subprocess.SubprocessError as exc:
                raise ValueError('could not read the selected adapter: %s' % exc) from exc
            addresses = dict(zip(link.decks, [str(ip.ip) for ip in selected]))
            if any(address not in macs for address in addresses.values()):
                raise ValueError('the selected adapter has no usable MAC address')
            broadcast = str(selected[0].network.broadcast_address)
            subnet = selected[0].network
        else:
            addresses = {n: '127.0.0.%d' % n for n in link.decks}
            macs = {address: bytes([2, 0xFA, 0x4E, 0xDE, 0xC0, n]) for n, address in addresses.items()}
            broadcast = '127.255.255.255'
            subnet = ipaddress.IPv4Network('127.0.0.0/8')
        link.reconnect(addresses, broadcast, macs, subnet)
        self.interface = name
        warning = ''
        if remember:
            try:
                folder = os.path.dirname(self.settings)
                os.makedirs(folder, exist_ok=True)
                fd, path = tempfile.mkstemp(prefix='network-', dir=folder)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as target:
                        json.dump({'interface': name}, target)
                    os.replace(path, self.settings)
                finally:
                    if os.path.exists(path):
                        os.unlink(path)
            except OSError as exc:
                warning = 'Connected, but could not remember the adapter: %s' % exc
        return {'current': self.current(), 'warning': warning}
