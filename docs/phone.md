# Using deckbench from a phone

Two different things, and only the first has been thought through to the end. Neither has been tried on a phone.

## 1. The phone is the screen, a small computer is the bench (recommended)

The bench needs to be on the Pro DJ Link network with an address of its own for each deck (see
[real-network.md](real-network.md)). A phone cannot give itself several addresses, a computer can. So put the bench on a
small machine cabled to the players' switch (a laptop, a Raspberry Pi, a mini PC) and open its page on the phone over Wi-Fi.

On the machine, with `--http-host 0.0.0.0` so that the phone can reach the page, and a token, so that nothing else on the Wi-Fi can
drive the decks:

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
