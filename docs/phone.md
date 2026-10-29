# Using deckbench from a phone

Phone access and a phone-only bench are different approaches. Neither has been validated on a physical phone yet.

## 1. The phone is the screen, a small computer is the bench (recommended)

The bench needs an address of its own for each deck on the Pro DJ Link network. Put it on a computer cabled to the
players' switch and open its page on the phone over Wi-Fi. See [real-network.md](real-network.md) for the separate
DJ network configuration, which is still manual.

Install the optional QR encoder once, from a checkout or extracted release:

    python -m pip install ".[phone]"

Start with `python -m deckbench --network-info` to find the DJ adapter's name and IPv4 address. With one deck, its
existing address can be used without adding aliases. On Windows and Linux, for example:

    python -m deckbench --phone --numbers 2 --on --dj-interface "Ethernet 2"

Replace the name with the DJ adapter's actual name and choose an unused player number. This selects already configured
addresses and their mask. It does not change the adapter. For more than one deck, the adapter needs a distinct address
for each deck. If it has too few addresses or multiple subnets, the command stops with an explanation.

Alternatively, start the bench with `--phone` and explicit DJ network addresses:

    python -m deckbench --phone --numbers 2,3 --on --bind 169.254.100.1,169.254.100.2 --netmask 255.255.0.0

This example assumes those addresses have already been added to the DJ adapter and are unused. It does not configure
the adapter. Choose addresses for the DJ adapter as described in the real-network guide.

Scan the terminal QR with the phone to open the hosted page with its connection details. `--phone` binds the page on all
interfaces, creates a token if none was provided and permits the hosted site. It guesses the phone-facing address from
the default route, which may be wrong on a machine with multiple networks. If the phone cannot reach it, use
`--phone-address <PC address on the phone's network>`. The QR package is optional. Without it the pairing link is printed
with an installation hint.

The phone and PC need a reachable path, such as the phone on the home Wi-Fi and the PC's normal Ethernet on that same
home network. Keep the DJ adapter on its own subnet. Guest Wi-Fi isolation or a firewall may prevent the connection.
The site may ask for local-network permission. If the hosted page cannot connect, open the PC-served page directly using
the address and token printed by the bench.

The QR and pairing link contain the token. Anyone who can read them and reach the server can control the bench. Do not
share screenshots or logs containing them. HTTP traffic on the local network is not encrypted. Use a trusted network.
Close the bench when finished.

The equivalent manual setup still works:

    python -m deckbench --numbers 2,3 --on \
        --bind 192.168.1.201,192.168.1.202 --netmask 255.255.255.0 \
        --http-host 0.0.0.0 --token auto

It prints the token and the address of the page. On the phone open `http://<the machine's Wi-Fi address>:8750/#token=<the token>`.
The page is laid out for narrow screens (checked at 500 px in a desktop browser, not on a phone) and has the decks, the loops, the cable, the mixer and the events.

The machine has two networks, the one with the players (Ethernet) and the one of the phone (Wi-Fi). They must be different
networks, or the players' broadcasts and the phone's browsing share one, which they should not.

## 2. The hosted page, as the screen

The site's page (commitcollective.cc/deckbench) is the same page. It asks for the address and the token of a bench, and
needs that bench to allow it:

    python -m deckbench ... --http-host 0.0.0.0 --allow-origin https://commitcollective.cc --token auto

Without `--allow-origin` the bench refuses a page of another site (any web page could otherwise drive a bench on your
network). A secure page (https) that calls a bench on `http://192.168...` is allowed by Chrome for an address on a private
network, and may ask for a permission to reach the local network. Other browsers can be stricter and then the page served
by the bench itself (option 1) is the way. The same page has a **demo** (`?demo`): a bench made of JavaScript, for looking at
the page with no network and no Python.

## 3. The phone is the bench (one device, not tried)

The idea: a Pixel with a USB Ethernet adapter on the players' switch, deckbench in Termux, the page in the phone's browser at
`http://localhost:8750/`. Deckbench is plain Python, with nothing to install.

    pkg install python git
    git clone <deckbench's repository>
    cd deckbench
    python -m deckbench --numbers 2 --on --bind <the phone's address on the Ethernet> --netmask 255.255.255.0

What stands in the way:

- **One address.** Without root a phone has one address on the Ethernet, and each simulated device needs its own. So it can
  be **one** deck, or one mixer, not a set. A bench of several decks needs option 1.
- **An address at all.** A network of CDJs has no DHCP server unless a router is there. The phone must get an address on the
  players' subnet (a static one, or a link-local 169.254.x.y that Android assigns itself on some versions). Whether a Pixel's USB
  Ethernet lets you set one, and which Android version does what, was not checked.
- **Which interface.** Android may route Termux's traffic out of the Wi-Fi or mobile data and not the Ethernet. A socket
  bound to the Ethernet address (`--bind`) should go out of it. That is the thing to try first.
- **Broadcasts.** The announcements are UDP broadcasts to the subnet's broadcast address. Android allows them from an app, but
  nothing here shows they leave through the Ethernet adapter.

If it works it is a handy one-deck test (a deck that is the master, for a player's SYNC). If it does not, option 1 does.
