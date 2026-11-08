# SPDX-License-Identifier: MIT OR Apache-2.0
"""PLAY/PAUSE and CUE pressed on a CDJ-3000 and a CDJ-2000NXS2, and each model's way of being started and stopped."""
import socket
import unittest
import unittest.mock

import test_player_control as controls
from deckbench.protocols import transport
from deckbench.scenario import Scenario, ScenarioError

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

    def test_a_hold_the_page_keeps_lasts(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        self.net.HOLD_LIMIT = 0.4
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(0.3)
            self.assertEqual(self.call("command", "cue-down")[0], 202)
            receiver.settimeout(2)
            self.received(receiver, 2)
            receiver.settimeout(0.3)
            for _ in range(4):                                       # 1.2 s, three times the limit, kept each 0.3 s
                self.assertEqual(self.call("command", "cue-hold"), (200, {"held": True}))
                with self.assertRaises(socket.timeout):
                    receiver.recv(2048)
            self.assertEqual(self.call("command", "cue-up"), (200, {"released": True}))
            self.assertEqual(self.call("command", "cue-hold"), (200, {"held": False}))  # late: presses nothing
        self.assertEqual(self.net.held, {})

    def test_play_while_cue_is_held_goes_through_the_hold(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(2)
            self.assertEqual(self.call("command", "cue-down")[0], 202)
            self.received(receiver, 2)
            self.assertEqual(self.call("command", "play-pause")[0], 202)
            self.assertEqual(self.received(receiver, 2), [TESTED["play-pause down"], TESTED["play-pause up"]])
            self.assertEqual(self.call("command", "cue-up"), (200, {"released": True}))
            self.assertEqual(self.received(receiver, 2), [transport.packet(0, 21).hex(), TESTED["disconnect"]])

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

    def test_a_quick_tap_is_let_go_after_its_press(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        sent, waits = [], []
        sender = self.net.decks[3]
        # cue-up comes while the press is on its way (during the settle): it is kept, and sent once CUE is down
        def pause(seconds):
            waits.append(seconds)
            if len(waits) == 1:                         # the settle, the first wait
                self.assertEqual(self.call("command", "cue-up"), (200, {"released": True}))
        with unittest.mock.patch.object(sender, "send", lambda sock, data, addr: sent.append(data.hex())),              unittest.mock.patch.object(self.net.runtime.stopping, "wait", pause):
            self.assertEqual(self.call("command", "cue-down")[1]["held"], False)
        self.assertEqual(sent, [TESTED["connect"], TESTED["cue down"], transport.packet(0, 21).hex(), TESTED["disconnect"]])
        self.assertGreater(waits[-1], 0)                    # held at least transport.HOLD before the release
        self.assertEqual(self.net.held, {})

    def test_a_device_with_the_controller_number_stops_it(self):
        self.as_model(b"CDJ-3000")
        self.call("arm", "1")
        device = next(iter(self.net.monitor.devices.values()))
        clash = dict(device, number=transport.CONTROLLER, ip="127.0.0.54", mac="02:00:00:00:00:54")
        self.net.monitor.devices[("127.0.0.54", transport.CONTROLLER)] = clash
        self.assertEqual(self.call("command", "cue")[0], 409)


class ScenarioSteps(unittest.TestCase):
    """A scenario's player and expect_player steps: the page's own controls on a real player, by its number."""
    setUp = controls.PlayerControl.setUp
    feed = controls.PlayerControl.feed
    call = controls.PlayerControl.call
    received = Buttons.received

    def run_steps(self, *steps):
        return [(ok, message) for _, ok, message in Scenario({"steps": list(steps)}).run(self.net.world)]

    def test_a_bad_player_step_is_refused_when_it_is_read(self):
        for step in ({"do": "player", "press": "cue"}, {"do": "player", "player": 2},
                     {"do": "player", "player": 2, "press": "cue", "load": 1}, {"do": "expect_player", "player": 2}):
            with self.subTest(step=step), self.assertRaises(ScenarioError):
                Scenario({"steps": [step]})

    def test_a_press_needs_player_control_and_a_player_there(self):
        (ok, message), = self.run_steps({"do": "player", "player": 2, "press": "play-pause"})
        self.assertFalse(ok)
        self.assertIn("Player control", message)
        (ok, message), = self.run_steps({"do": "player", "player": 4, "press": "play-pause"})
        self.assertEqual((ok, message), (False, "no player 4 on the link"))

    def test_a_press_and_a_held_cue_reach_the_player(self):
        self.call("arm", "1")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((self.ip, self.net.ports.beat))
            receiver.settimeout(2)
            results = self.run_steps({"at": 0, "do": "player", "player": 2, "press": "play-pause"},
                                     {"at": 0, "do": "player", "player": 2, "press": "cue", "hold": 0.3})
            self.assertTrue(all(ok for ok, _ in results), results)
            self.assertEqual(self.received(receiver, 8),
                             [LEGACY["connect"], LEGACY["play-pause down"], LEGACY["play-pause up"], LEGACY["disconnect"],
                              LEGACY["connect"], LEGACY["cue down"], LEGACY["cue up"], LEGACY["disconnect"]])
        self.assertEqual(self.net.held, {})

    def test_a_load_names_its_source_and_slot(self):
        self.call("arm", "1")
        with unittest.mock.patch.object(self.net, "load_player_track", return_value=(202, {"sent": True})) as load:
            (ok, _), = self.run_steps({"do": "player", "player": 2, "load": 205})
            self.assertTrue(ok)
            self.assertEqual(load.call_args.args[1:], ("205", {"number": ["2"], "source": ["2"], "slot": ["3"]}))
            self.run_steps({"do": "player", "player": 2, "load": 7, "source": 1, "slot": "sd"})
            self.assertEqual(load.call_args.args[2], {"number": ["2"], "source": ["1"], "slot": ["2"]})

    def test_expect_player_reads_what_the_player_says(self):
        results = self.run_steps({"do": "expect_player", "player": 2, "match": {"online": True, "play": False}, "within": 1},
                                 {"do": "expect_player", "player": 2, "match": {"play": True}, "within": 0.2},
                                 {"do": "expect_player", "player": 4, "match": {"online": True}, "within": 0.2})
        self.assertEqual([ok for ok, _ in results], [True, False, False])


if __name__ == "__main__":
    unittest.main()
