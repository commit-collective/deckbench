# SPDX-License-Identifier: MIT OR Apache-2.0
import struct
import unittest
from unittest.mock import patch

from deckbench.adapters.djs1000_emu import Djs1000Emulator


class EmulatorMessages(unittest.TestCase):
    def test_project_messages_preserve_lamps_and_controls(self):
        adapter = Djs1000Emulator()
        observed = {}
        lamps = bytearray(128)
        lamps[0x6a] = 5

        def packet(kind, data, y=0, rows=0, width=0):
            return struct.pack('<BBHHH', ord(kind), 0, y, rows, width) + data

        project = 'Test / Café.prj'.encode('utf-8')
        stream = (packet('S', bytes(4), rows=1, width=1) + packet('P', b'') +
                  packet('P', project, y=len(project)) + packet('A', bytes(16), y=2) +
                  packet('L', lamps))

        class Peer:
            def __init__(self):
                self.pending = stream
                self.sent = []

            def settimeout(self, value):
                pass

            def recv(self, size):
                if not self.pending:
                    observed.update(adapter.state())
                    observed['pressed'] = adapter.press('master')
                    adapter.stopping = True
                    raise ConnectionError('Test complete')
                data, self.pending = self.pending[:min(size, 2)], self.pending[min(size, 2):]
                return data

            def sendall(self, data):
                self.sent.append(data)

            def close(self):
                pass

        peer = Peer()
        with patch('deckbench.adapters.djs1000_emu.socket.create_connection', return_value=peer), \
             patch('deckbench.adapters.djs1000_emu.time.sleep'):
            adapter.run()
        self.assertTrue(observed.get('adapter.connected'))
        self.assertTrue(observed.get('lamp.sync'))
        self.assertTrue(observed.get('lamp.master'))
        self.assertEqual(observed.get('pressed'), (True, ''))
        self.assertEqual(peer.sent, [b'tap 6 6\n'])


if __name__ == '__main__':
    unittest.main()
