# On a real network

By default the decks are on the loopback (127.0.0.n), which only a client on
the same machine, in the same network namespace, sees. To show them to a real
unit (a DJS-1000, a CDJ, a mixer, software on another machine) each deck needs
**an address of its own on the network's subnet**, and the broadcasts have to
go to that network's broadcast address.

    python -m deckbench --numbers 2,3,4 --on \
        --bind 192.168.1.201,192.168.1.202,192.168.1.203 --netmask 255.255.255.0

`--bind` gives the addresses of the decks in the order of `--numbers`;
`--netmask` (default 255.255.255.0) finds the broadcast address from the first
one (192.168.1.255 here), or give it with `--broadcast`. The decks announce
themselves with those addresses, play, and answer the database there.

## 1. Choose the addresses

They must be on the same subnet as the unit and not in use. The unit's own
address is shown in the page once it has been heard ("Unit under test: player
1 ... (192.168.1.x)"), and by your router's list of clients.

- **A router or switch with DHCP**: take three free addresses of its range, outside
  its DHCP pool if you can (192.168.1.201-203 if the pool is 100-199).
- **A cable straight between the computer and the unit**: both take a
  link-local address (169.254.x.y, mask 255.255.0.0) when there is no DHCP.
  The computer's is shown by `ipconfig` / `ip addr`; the unit's, in the page
  once it has been heard. Use 169.254.100.1-3 and `--netmask 255.255.0.0`.

Player numbers: not the unit's (it is player 1 by default, `PLAYER No.` on
its home screen), and for a real CDJ network, not one in use.

## 2. Give the computer those addresses

An alias on the network card the unit is reached by (as an administrator).

Windows (the card's name is in `ipconfig`):

    netsh interface ipv4 add address name="Ethernet" address=192.168.1.201 mask=255.255.255.0
    netsh interface ipv4 add address name="Ethernet" address=192.168.1.202 mask=255.255.255.0
    netsh interface ipv4 add address name="Ethernet" address=192.168.1.203 mask=255.255.255.0

and to remove them afterwards:

    netsh interface ipv4 delete address name="Ethernet" address=192.168.1.201

Linux:

    sudo ip addr add 192.168.1.201/24 dev eth0     # and .202, .203
    sudo ip addr del 192.168.1.201/24 dev eth0     # to remove

macOS: `sudo ifconfig en0 alias 192.168.1.201 netmask 255.255.255.0`.

## 3. Run it where the network is

Run the bench on the machine that has the network card (on Windows, with
Windows' Python, not WSL: WSL 2 is on a network of its own behind a NAT, which
does not carry broadcasts to the real one unless WSL uses mirrored
networking). The page is at <http://127.0.0.1:8750/>.

The firewall may ask to let Python through on private networks: allow it (UDP
50000-50002 and TCP 12523 and 1051 are what the decks use).

## 4. Check

- The page says "Unit under test: player N (address)" within a few seconds
  of the unit being on the network: the bench hears its keep-alive.
- Switch a deck on, with its PLAY and MASTER: the unit's SYNC and MASTER work
  (with no deck on they say "No LINKED Players found").
- A mod or software that reads the decks' titles asks the database at the
  deck's address.

## If nothing is heard

- No "Unit under test": the broadcast address is probably wrong (give it
  with `--broadcast`), or a firewall drops UDP 50000, or the alias is on a
  different network card than the unit.
- The unit sees the decks but not their tracks: TCP 12523 and 1051 are blocked.
- Decks that vanish after a few seconds: the keep-alive (every 2 s, to the
  broadcast address) does not reach the unit.

## What has been checked

The addresses, the broadcast and the unit's side of it, with the DJS-1000
emulator on a Linux host (decks on aliases of the host's network card, the
emulated unit on that network): the unit sees the decks, follows a master, hands
the master role over and back. Windows and macOS aliases, and a real unit on a
real cable, have not been tried.
