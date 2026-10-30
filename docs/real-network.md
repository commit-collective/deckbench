# On a real network

Run Deckbench on a Windows or Linux computer connected by Ethernet to the same switch as the players. Use the
computer's built-in Ethernet port, a dock or a USB Ethernet adapter. A second Ethernet adapter is optional.

## Connect the computer

There are two connections to think about:

- **DJ connection:** Ethernet from the computer to the players' switch. This carries Pro DJ Link discovery, beats and status.
- **Browser connection:** the path from your browser to that computer. On the computer itself, no extra connection is
  needed. A phone can reach it over the home network, through the computer's Wi-Fi or another Ethernet port.

For example, a laptop can use Ethernet for the players and Wi-Fi for internet and phone access. A desktop whose only
Ethernet port is already connected to the home router can use a second Ethernet port or USB adapter for an isolated
DJ switch. If the players and computer already share the same wired LAN, that connection can serve both purposes.

Deckbench itself does not need internet access. Loading the hosted browser page does. An isolated DJ network and a
home network should use different IP subnets. Keep the home connection's default gateway, and do not add a gateway
to the isolated DJ connection. Do not bridge the two connections or enable internet sharing for this setup.

## Select the DJ connection

Here, **DJ interface** means the Ethernet connection cabled to the players, regardless of whether it is built in or USB.
Use `python -m deckbench --network-info` to find its name and IPv4 address. Names are assigned by the operating system,
not by Deckbench. For one virtual player, use its existing address without adding another:

```powershell
# Windows example
python -m deckbench --numbers 3 --dj-interface "Ethernet"
```

```sh
# Linux example
python -m deckbench --numbers 3 --dj-interface enp3s0
```

Replace the interface name with the one shown on your computer and choose an unused player number. Add `--phone`
to pair a phone, as described in [phone.md](phone.md). Neither command changes adapter settings.

Real-network interface selection and MAC lookup currently support Windows and Linux. Native macOS real-network
operation is not supported by the current MAC lookup. A Linux VM needs direct access to the DJ Ethernet interface,
such as USB passthrough, rather than ordinary NAT networking. That VM setup has not been validated.

## Addresses and additional virtual players

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

Phone access and DJ link are separate. `--phone`, `--http-host` and `--allow-origin` do not put decks on the DJ
network. Without `--dj-interface` or `--bind`, decks remain on loopback. The monitor listens on wildcard sockets, so it may still hear
broadcasts on the computer's network interfaces, subject to firewall and OS behavior. Hearing a device is not proof
that a simulated deck can reach it.

## 1. Choose the addresses

They must be on the same subnet as the unit and not in use. The unit's own
address is shown in the page once it has been heard ("Unit under test: player
1 ... (192.168.1.x)"), and by your router's list of clients.

- **A network with a DHCP server**, usually a router: take free addresses on its subnet, outside
  its DHCP pool if you can (192.168.1.201-203 if the pool is 100-199).
- **An isolated switch or direct cable without DHCP**: players typically use
  link-local addresses (169.254.x.y, mask 255.255.0.0). The computer also needs an address on that subnet,
  assigned automatically if its OS supports that or configured manually.
  The computer's is shown by `ipconfig` / `ip addr`; the unit's, in the page
  once it has been heard. Use 169.254.100.1-3 and `--netmask 255.255.0.0`.

If you need only one simulated deck, its `--bind` address can be the DJ interface's existing IPv4 address.
Additional decks need additional addresses on that same interface, not additional Ethernet adapters.
Check addresses and player numbers for conflicts. These commands do not detect every device or prevent a collision.
On Windows and Linux, simulated decks use the selected adapter's actual MAC address. Loopback tests retain synthetic
MAC addresses. Do not assume an observed announcement proves full compatibility.

Player numbers: not the unit's (it is player 1 by default, `PLAYER No.` on
its home screen), and for a real CDJ network, not one in use.

## 2. Give the computer those addresses

An alias on the network card the unit is reached by (as an administrator).
Skip this section when using one deck with the interface's existing address.

Windows (the card's name is in `ipconfig`):

    netsh interface ipv4 add address name="Ethernet" address=192.168.1.201 mask=255.255.255.0
    netsh interface ipv4 add address name="Ethernet" address=192.168.1.202 mask=255.255.255.0
    netsh interface ipv4 add address name="Ethernet" address=192.168.1.203 mask=255.255.255.0

and to remove them afterwards:

    netsh interface ipv4 delete address name="Ethernet" address=192.168.1.201

Linux:

    sudo ip addr add 192.168.1.201/24 dev eth0     # and .202, .203
    sudo ip addr del 192.168.1.201/24 dev eth0     # to remove

## 3. Run it where the network is

On Windows, run Python from PowerShell or Command Prompt. On Linux, use a terminal on the computer connected to
the players. The local browser page is at <http://127.0.0.1:8750/>. Phone access is optional.

### Windows firewall

An isolated DJ adapter is often a Public network. A Python exception for Private networks does not cover it.
On the computer physically connected to the DJ switch, open PowerShell as administrator, enter the checkout directory
and install a scoped rule:

```powershell
.\tools\windows-firewall.ps1 -Action Install -InterfaceAlias "Ethernet"
```

The script finds the current `python` executable and the adapter's IPv4 subnet. It allows inbound UDP 50000 through
50002 only for that executable, adapter and subnet, across Windows network profiles. It leaves adapter addressing and
the default gateway unchanged. Use `-Python "C:\path\to\python.exe"` if the bench uses another interpreter.
Use `-WhatIf` to preview installation. The rule persists across restarts.

For metadata requests from physical players, add `-IncludeMetadata` when installing. This also allows TCP 1051 and
12523 under the same restrictions. This is metadata access, not network audio or a virtual USB drive.
Phone HTTP access is separate and is not opened by this script.
Replace `Ethernet` with the name of your DJ interface. The Windows firewall helper is only for Windows. On Linux,
check any active firewall for the same UDP ports and optional metadata TCP ports.

Inspect the installed rules, or remove them when no longer needed:

```powershell
.\tools\windows-firewall.ps1 -Action Show
.\tools\windows-firewall.ps1 -Action Remove
```

Removal needs administrator rights. If Python, the adapter name or its subnet changes, remove and reinstall the rules.
After installing the permanent rule, an earlier troubleshooting rule can be removed:

```powershell
Remove-NetFirewallRule -Name "Deckbench-ProDJLink-UDP-Test"
```

Run these commands on the DJ-connected PC, even if development happens on another computer.

## 4. Check

- The page says "Unit under test: player N (address)" within a few seconds
  of the unit being on the network: the bench hears its keep-alive.
- Switch a deck on, with its PLAY and MASTER: the unit's SYNC and MASTER work
  (with no deck on they say "No LINKED Players found").
- A mod or software that reads the decks' titles asks the database at the
  deck's address.

## If nothing is heard

- **WSL, containers or virtual machines:** a virtual NAT network does not automatically expose the computer's physical
  DJ interface. For real hardware on Windows, use Windows Python. WSL means Windows Subsystem for Linux and is not
  required by Deckbench. Its default networking uses NAT, while mirrored mode changes how interfaces are exposed.
  Mirrored-mode Pro DJ Link has not been validated here. See [Microsoft's networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking).
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
the master role over and back. On Windows with physical players, a CDJ reacted
to a simulated deck but reported an older-firmware warning and a link access
error. A scoped Public-profile UDP firewall rule resolved reception, and the
phone showed the real devices and their statuses. Master and sync changes,
the compatibility flag and the absent-media flags still need a hardware check.
Native macOS real-network operation and Linux VM Ethernet passthrough have not been validated.

## Master and sync with physical players

Use a free player number and enable the virtual deck before expecting full player status. Physical players normally
send detailed status only to announced peers. With every virtual deck off, broadcast beats still provide tempo and
bar position, but master and sync flags may be unavailable.

A synced virtual deck follows the tempo and bar of a physical CDJ master. Pressing MASTER on a virtual deck requests
the role from the physical master and waits for its status to name the new master. An unanswered request produces a
`handoff_timeout` event and leaves the virtual deck out of the master role. A physical player can likewise request the
role from a virtual master. SYNC must be enabled on each follower, as on real players.

The bench exchanges control and timing packets. It does not route audio into physical players or serve virtual tracks
as USB media. The CDJ-2000NXS2, XDJ-1000MK2 and DJM-900NXS2 still need validation as a combined setup.

### Hardware check

With two players using numbers 1 and 2, use virtual player 3. Confirm the actual numbers on the players first.

```sh
python -m deckbench --phone --numbers 3 --dj-interface "Ethernet"
```

This uses a Windows example interface name. On Linux, substitute the name reported by `--network-info`.

1. Leave virtual player 3 off. Play an analyzed track on a physical player. Its broadcast BPM and beat lamps should
   update on the phone. Detailed status may still say `no status yet`.
2. Enable virtual player 3. Confirm that both physical players and the mixer appear and their status updates.
   Check that the older-firmware warning and LINK ACCESS ERROR no longer appear.
3. Make a physical player master, then enable PLAY and SYNC on virtual player 3. Change the physical master's tempo.
   Check that player 3 follows its BPM and bar.
4. Press MASTER on player 3. Check that the physical player releases MASTER. Enable its SYNC, change player 3's tempo
   and check that the physical player's displayed tempo follows it.
5. Press MASTER on the other physical player. Check that player 3 releases MASTER and follows when its SYNC is on.
6. Disable player 3. The phone should continue showing broadcast beats, while detailed status may expire.

If a step fails, keep the bench's event and packet logs and identify the failing step. Local simulated tests do not
establish physical compatibility. A `handoff_timeout` means the requested transfer was not confirmed.
