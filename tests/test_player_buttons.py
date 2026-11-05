# SPDX-License-Identifier: MIT OR Apache-2.0
"""PLAY/PAUSE and CUE pressed on a CDJ-3000, and each model's way of being started and stopped."""
import socket
import unittest

import test_player_control as controls
from deckbench.protocols import transport

# The datagrams of the test that worked on CDJ-3000 firmware (cdj3k-emu, 2026-11-05), as its logs recorded them.
TESTED = {
    "connect": "5173707431576d4a4f4c076465636b62656e63682070726f62650000000000010036002a000100000000",
    "disconnect": "5173707431576d4a4f4c076465636b62656e63682070726f62650000000000010036002a000200000000",
    "play-pause down": "5173707431576d4a4f4c076465636b62656e63682070726f626500000000000100360030000000000001001400010000",
    "play-pause up": "5173707431576d4a4f4c076465636b62656e63682070726f626500000000000100360030000000000001001400000000",
    "cue down": "5173707431576d4a4f4c076465636b62656e63682070726f626500000000000100360030000000000001001500010000",
}


class Packets(unittest.TestCase):
    def test_the_bytes_are_the_tested_ones(self):
        self.assertEqual(transport.packet(transport.CONNECT).hex(), TESTED["connect"])
        self.assertEqual(transport.packet(transport.DISCONNECT).hex(), TESTED["disconnect"])
        self.assertEqual(transport.packet(0, 20, True).hex(), TESTED["play-pause down"])
        self.assertEqual(transport.packet(0, 20).hex(), TESTED["play-pause up"])
        self.assertEqual(transport.packet(0, 21, True).hex(), TESTED["cue down"])

    def test_release_and_disconnect_follow_a_failed_press(self):
        sent = []

        def send(data):
            sent.append(data)
            if len(sent) == 2:
                raise OSError("press lost")
        with self.assertRaises(OSError):
            transport.press(send, "cue", lambda seconds: None)
        self.assertEqual([d.hex() for d in sent[2:]], [transport.packet(0, 21).hex(), TESTED["disconnect"]])


class Buttons(unittest.TestCase):
    setUp = controls.PlayerControl.setUp
    feed = controls.PlayerControl.feed
    call = controls.PlayerControl.call

    def as_model(self, name):
        self.net.monitor.devices.clear()
        self.player.name = name
        self.feed()
        return self.net.info()["devices"][0]

    def test_each_model_gets_its_own_method(self):
        for name, method in ((b"CDJ-2000NXS2", "fader"), (b"CDJ-3000", "buttons"), (b"CDJ-3000X", "buttons"),
                             (b"XDJ-XZ", "")):
            with self.subTest(model=name):
                device = self.as_model(name)
                self.assertEqual(device["transport_method"], method)
                self.assertEqual(device["fader_start_supported"], method == "fader")

    def test_a_press_is_four_datagrams_from_the_beat_port(self):
        self.as_model(b"CDJ-3000")
        self.assertEqual(self.call("command", "play-pause")[0], 403)          # not armed
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(2)
            self.assertEqual(self.call("command", "play-pause"), (202, {"sent": True, "confirmed": False}))
            got = [receiver.recvfrom(1024) for _ in range(4)]
        self.assertEqual([data.hex() for data, _ in got],
                         [TESTED["connect"], TESTED["play-pause down"], TESTED["play-pause up"], TESTED["disconnect"]])
        self.assertEqual({source[1] for _, source in got}, {self.net.ports.beat})

    def test_the_wrong_method_is_refused(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        code, body = self.call("command", "start")
        self.assertEqual(code, 400)
        self.assertIn("play-pause", body["error"])
        self.as_model(b"CDJ-2000NXS2")
        self.call("arm", "1")
        code, body = self.call("command", "cue")
        self.assertEqual(code, 400)
        self.assertIn("start and stop", body["error"])

    def test_a_device_with_the_controller_number_stops_it(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        device = next(iter(self.net.monitor.devices.values()))
        clash = dict(device, number=transport.CONTROLLER, ip="127.0.0.54", mac="02:00:00:00:00:54")
        self.net.monitor.devices[("127.0.0.54", transport.CONTROLLER)] = clash
        self.assertEqual(self.call("command", "cue")[0], 409)


if __name__ == "__main__":
    unittest.main()
