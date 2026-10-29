# SPDX-License-Identifier: MIT OR Apache-2.0
import io
import ipaddress
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from deckbench import phone
from deckbench.testing import Bench


class Pairing(unittest.TestCase):
    def test_pairing_fragment_and_escape(self):
        url = phone.pairing_url("192.168.4.10", 8750, "a+b &secret")
        parts = urlsplit(url)
        self.assertEqual(parts.scheme, "https")
        self.assertEqual(parts.netloc, "commitcollective.cc")
        self.assertEqual(parts.query, "")
        self.assertEqual(parse_qs(parts.fragment), {"bench": ["http://192.168.4.10:8750"], "token": ["a+b &secret"]})

    def test_bad_addresses_and_token_are_rejected(self):
        for address in ("127.0.0.1", "0.0.0.0", "224.0.0.1", "invalid", None):
            with self.subTest(address=address), self.assertRaises((ValueError, TypeError)):
                phone.pairing_url(address, 8750, "secret")
        with self.assertRaises(ValueError):
            phone.pairing_url("192.168.1.2", 8750, "")

    def test_qr_fallback_does_not_break_pairing(self):
        with mock.patch.dict(sys.modules, {"qrcode": None}):
            self.assertFalse(phone.print_qr("https://example.test/#token=secret", io.StringIO()))

    @mock.patch("deckbench.phone.subprocess.run")
    def test_network_info_is_read_only(self, run):
        data = '[{"InterfaceAlias":"DJ USB","IPAddress":"169.254.1.2","PrefixLength":16}]'
        run.return_value = mock.Mock(returncode=0, stdout=data, stderr="")
        with mock.patch.object(phone.sys, "platform", "win32"), mock.patch.object(phone, "route_address", return_value=None):
            out = io.StringIO()
            self.assertEqual(phone.network_info(out), 0)
        self.assertIn("DJ USB: 169.254.1.2/16, mask 255.255.0.0", out.getvalue())
        self.assertEqual(run.call_args.args[0][0], "powershell")

    @mock.patch("deckbench.phone.socket.socket")
    def test_route_address_and_failure(self, socket):
        sock = socket.return_value.__enter__.return_value
        sock.getsockname.return_value = ("192.168.1.10", 1234)
        self.assertEqual(phone.route_address(), "192.168.1.10")
        sock.connect.assert_called_once_with(("192.0.2.1", 9))
        sock.connect.side_effect = OSError("no route")
        self.assertIsNone(phone.route_address())

    @mock.patch("deckbench.phone.interfaces")
    def test_dj_interface_requires_enough_addresses_on_one_subnet(self, interfaces):
        interfaces.return_value = [("DJ", ipaddress.IPv4Interface("169.254.1.2/16")),
                                   ("DJ", ipaddress.IPv4Interface("169.254.1.3/16")),
                                   ("Home", ipaddress.IPv4Interface("192.168.1.10/24"))]
        self.assertEqual([str(x.ip) for x in phone.dj_interface("DJ", 2)], ["169.254.1.2", "169.254.1.3"])
        with self.assertRaisesRegex(ValueError, "3 decks"):
            phone.dj_interface("DJ", 3)
        with self.assertRaisesRegex(ValueError, "no preferred"):
            phone.dj_interface("Missing", 1)
        interfaces.return_value.append(("DJ", ipaddress.IPv4Interface("10.1.1.2/24")))
        with self.assertRaisesRegex(ValueError, "multiple subnets"):
            phone.dj_interface("DJ", 1)

    def test_phone_mode_serves_the_allowed_origin_with_a_token(self):
        with Bench(numbers=[2], args=["--phone", "--phone-address", "192.0.2.10", "--token", "test-token"]) as bench:
            with self.assertRaises(HTTPError) as error:
                urlopen(bench.url + "api/ready", timeout=5)
            self.assertEqual(error.exception.code, 401)
            request = Request(bench.url + "api/ready?token=test-token", headers={"Origin": phone.SITE})
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), phone.SITE)
            output = bench.output()
            self.assertIn("DJ link: loopback only", output)
            self.assertIn("phone pairing link: " + phone.pairing_url("192.0.2.10", int(urlsplit(bench.url).port),
                                                                    "test-token"), output)

    @mock.patch("deckbench.cli.time.sleep", side_effect=KeyboardInterrupt)
    @mock.patch("deckbench.cli.Prolink")
    @mock.patch("deckbench.phone.dj_interface")
    def test_cli_uses_selected_address_and_mask(self, select, prolink, sleep):
        from deckbench.cli import main

        select.return_value = [ipaddress.IPv4Interface("169.254.1.2/16")]
        self.assertEqual(main(["--dj-interface", "DJ", "--numbers", "2", "--http-port", "-1"]), 0)
        select.assert_called_once_with("DJ", 1)
        self.assertEqual(prolink.call_args.kwargs["addresses"], {2: "169.254.1.2"})
        self.assertEqual(prolink.call_args.kwargs["broadcast"], "169.254.255.255")


if __name__ == "__main__":
    unittest.main()
