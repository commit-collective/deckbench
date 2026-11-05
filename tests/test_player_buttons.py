# SPDX-License-Identifier: MIT OR Apache-2.0
"""PLAY/PAUSE and CUE pressed on a CDJ-3000 and a CDJ-2000NXS2, and each model's way of being started and stopped."""
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
# The NXS2's little-endian format, controller slot 2, as the probe's logs of the test on a physical CDJ-2000NXS2 recorded it.
LEGACY = {
    "connect": "5173707431576d4a4f4c076465636b62656e63682070726f62650000000000010036002a010002000000",
    "disconnect": "5173707431576d4a4f4c076465636b62656e63682070726f62650000000000010036002a020002000000",
    "play-pause down": "5173707431576d4a4f4c076465636b62656e63682070726f626500000000000100360030000002000100140000010000",
    "play-pause up": "5173707431576d4a4f4c076465636b62656e63682070726f626500000000000100360030000002000100140000000000",
    "cue down": "5173707431576d4a4f4c076465636b62656e63682070726f626500000000000100360030000002000100150000010000",
    "cue up": "5173707431576d4a4f4c076465636b62656e63682070726f626500000000000100360030000002000100150000000000",
}


class Packets(unittest.TestCase):
    def test_the_bytes_are_the_tested_ones(self):
        self.assertEqual(transport.packet(transport.CONNECT).hex(), TESTED["connect"])
        self.assertEqual(transport.packet(transport.DISCONNECT).hex(), TESTED["disconnect"])
        self.assertEqual(transport.packet(0, 20, True).hex(), TESTED["play-pause down"])
        self.assertEqual(transport.packet(0, 20).hex(), TESTED["play-pause up"])
        self.assertEqual(transport.packet(0, 21, True).hex(), TESTED["cue down"])

    def test_the_legacy_bytes_are_the_tested_ones(self):
        self.assertEqual(transport.packet(transport.CONNECT, slot=2).hex(), LEGACY["connect"])
        self.assertEqual(transport.packet(transport.DISCONNECT, slot=2).hex(), LEGACY["disconnect"])
        for button, key in (("play-pause", 20), ("cue", 21)):
            self.assertEqual(transport.packet(0, key, True, 2).hex(), LEGACY[button + " down"])
            self.assertEqual(transport.packet(0, key, False, 2).hex(), LEGACY[button + " up"])
        for slot in (0, 5):
            with self.assertRaises(ValueError):
                transport.packet(transport.CONNECT, slot=slot)

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
        for name, method, fader in ((b"CDJ-2000NXS2", "buttons", True), (b"XDJ-1000MK2", "buttons", True), (b"CDJ-2000NXS", "fader", True),
                                    (b"CDJ-3000", "buttons", False), (b"CDJ-3000X", "buttons", False), (b"XDJ-XZ", "", False)):
            with self.subTest(model=name):
                device = self.as_model(name)
                self.assertEqual(device["transport_method"], method)
                self.assertEqual(device["fader_start_supported"], fader)

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
        self.as_model(b"CDJ-2000NXS")
        self.call("arm", "1")
        code, body = self.call("command", "cue")
        self.assertEqual(code, 400)
        self.assertIn("start and stop", body["error"])

    def test_an_nxs2_press_is_in_its_own_format(self):
        for name in (b"CDJ-2000NXS2", b"XDJ-1000MK2"):
            with self.subTest(model=name):
                self.as_model(name)
                self.press_in_legacy_format()

    def press_in_legacy_format(self):
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(2)
            self.assertEqual(self.call("command", "play-pause")[0], 202)
            self.assertEqual(self.received(receiver, 4),
                             [LEGACY["connect"], LEGACY["play-pause down"], LEGACY["play-pause up"], LEGACY["disconnect"]])
            self.assertEqual(self.call("command", "cue-down")[0], 202)
            self.assertEqual(self.received(receiver, 2), [LEGACY["connect"], LEGACY["cue down"]])
            self.assertEqual(self.call("command", "cue-up"), (200, {"released": True}))
            self.assertEqual(self.received(receiver, 2), [LEGACY["cue up"], LEGACY["disconnect"]])

    def test_an_nxs2_keeps_fader_start(self):
        self.as_model(b"CDJ-2000NXS2")
        self.call("arm", "1")
        self.assertEqual(self.call("command", "start")[0], 200)

    def received(self, receiver, count):
        return [receiver.recvfrom(1024)[0].hex() for _ in range(count)]

    def test_cue_is_held_until_let_go(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(2)
            code, body = self.call("command", "cue-down")
            self.assertEqual((code, body["held"]), (202, True))
            self.assertEqual(self.received(receiver, 2), [TESTED["connect"], TESTED["cue down"]])
            self.assertEqual(self.call("command", "cue-down"), (200, {"held": True}))      # a second down sends nothing
            self.assertEqual(self.call("command", "cue")[0], 409)                         # nor a tap while it is held
            self.assertEqual(self.call("command", "cue-up"), (200, {"released": True}))
            self.assertEqual(self.received(receiver, 2), [transport.packet(0, 21).hex(), TESTED["disconnect"]])
            self.assertEqual(self.call("command", "cue-up"), (200, {"released": False}))
        self.assertEqual(self.net.held, {})

    def test_a_hold_the_page_never_ends_is_let_go(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        self.net.HOLD_LIMIT = 0.3
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(3)
            self.assertEqual(self.call("command", "cue-down")[0], 202)
            self.received(receiver, 2)
            self.assertEqual(self.received(receiver, 2), [transport.packet(0, 21).hex(), TESTED["disconnect"]])
        self.assertEqual(self.net.held, {})

    def test_stopping_the_bench_lets_go(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(2)
            self.call("command", "cue-down")
            self.received(receiver, 2)
            self.net.stop()
            self.assertEqual(self.received(receiver, 2), [transport.packet(0, 21).hex(), TESTED["disconnect"]])

    def test_holding_is_only_for_players_that_take_presses(self):
        self.as_model(b"CDJ-2000NXS")
        self.call("arm", "1")
        self.assertEqual(self.call("command", "cue-down")[0], 400)
        self.assertEqual(self.call("command", "cue-up"), (200, {"released": False}))     # letting go is never refused

    def test_a_device_with_the_controller_number_stops_it(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        device = next(iter(self.net.monitor.devices.values()))
        clash = dict(device, number=transport.CONTROLLER, ip="127.0.0.54", mac="02:00:00:00:00:54")
        self.net.monitor.devices[("127.0.0.54", transport.CONTROLLER)] = clash
        self.assertEqual(self.call("command", "cue")[0], 409)


if __name__ == "__main__":
    unittest.main()
