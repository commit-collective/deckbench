# On a real network

You can choose the adapter in the browser's **Network → DJ network adapter**
panel instead of passing `--dj-interface`. Start with the unused player number
you need, for example `python -m deckbench --numbers 3`, then select the wired
adapter and press Reconnect. For phone access, add `--phone` as before.
The picker lists adapters on the server computer, including when using a phone.
Switch off the simulated decks and mixer before reconnecting. No adapter
addresses or firewall rules are changed. Each configured simulated deck needs
its own existing IPv4 address, so a four-deck launch needs four addresses.
Remembered choices are offered next time, not connected automatically.

Run Deckbench on a Windows, Linux or macOS computer connected by Ethernet to the same switch as the players. Use the
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

Real-network interface selection and MAC lookup support Windows, Linux and macOS. For Mac-specific instructions and
validation limits, see [macos.md](macos.md). A Linux VM needs direct access to the DJ Ethernet interface,
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
On Windows, Linux and macOS, simulated decks use the selected adapter's actual MAC address. Loopback tests retain synthetic
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
Replace `Ethernet` with the name of your DJ interface. Name several to cover each with one rule.

A program that bridges the DJ adapter (cdj3k-emu does) moves its address to a `Network Bridge` adapter while it runs.
The DJ adapter is then not an IP interface, which a rule cannot name, and the bridge comes and goes with the program.
For one rule that covers both states, add `-AnyWired`: the rule applies to every wired adapter, still only for this
Python, these ports and the DJ subnet. Name whichever adapter has the address at the time:

```powershell
.\tools\windows-firewall.ps1 -Action Install -InterfaceAlias "Network Bridge" -AnyWired
```

If PowerShell refuses to run the script ("running scripts is disabled"), run it once without changing the policy:
`powershell -ExecutionPolicy Bypass -File .\tools\windows-firewall.ps1 ...`.
The Windows firewall helper is only for Windows. On Linux,
check any active firewall for the same UDP ports and optional metadata TCP ports.

Inspect the installed rules, or remove them when no longer needed:

```powershell
.\tools\windows-firewall.ps1 -Action Show
.\tools\windows-firewall.ps1 -Action Remove
```

Removal needs administrator rights. If Python, the adapter name or its subnet changes, install again: it replaces its own rules.
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
- `PermissionError: [WinError 10013]` when the page's server starts, on Windows: something else holds port 8750,
  or Windows reserves it. With WSL in mirrored mode, a bench running in WSL (the DJS-1000 emulator starts one) shares
  Windows' ports. Check with `netstat -ano | findstr :8750` and
  `netsh interface ipv4 show excludedportrange protocol=tcp`. Stop the other bench, or start this one with
  `--http-port 8751`.
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
Native macOS adapter support is implemented but physical operation and Linux VM Ethernet passthrough remain unvalidated.

## Master and sync with physical players

Use a free player number and enable the virtual deck before expecting full player status. Physical players normally
send detailed status only to announced peers. With every virtual deck off, broadcast beats still provide tempo and
bar position, but master and sync flags may be unavailable.

A synced virtual deck follows the tempo and bar of a physical CDJ master. Pressing MASTER on a virtual deck requests
the role from the physical master and waits for its status to name the new master. An unanswered request produces a
`handoff_timeout` event and leaves the virtual deck out of the master role. A physical player can likewise request the
role from a virtual master. SYNC must be enabled on each follower, as on real players.

A become-master command can arrive before its sender's own MASTER status. If no
master is known, the virtual player still claims immediately. For one second it
remembers that command's sender. If the same player then announces MASTER, the
bench drops its conflicting claim and requests a normal handoff. The
`master_reconciled` event identifies this correction. Unrelated players and
announcements outside that window do not trigger it. An unanswered handoff leaves
the bench out of the role rather than restoring two masters.

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

## Trying player transport control

Use the PC-served page for unreleased controls. Leave the simulated mixer off, particularly with a real DJM present.
**Player control** in Settings is on by default, and off with `--observe`. While it is on, an eligible player's card has
switches like a bench deck's: PLAY/PAUSE, CUE, SYNC and MASTER on models that take button presses, START and STOP
(fader start) on the others. No command is sent until a switch is pressed. Stop is not pause-in-place.

On tested hardware, Start is accepted only when stopped at the cue point, not while playing or
paused elsewhere. Stop playing track returns to cue while playing, but does nothing while paused away from cue. These are
conditional fader-start commands, not general PLAY and CUE buttons. An ignored command does not mean the API failed.

Start and Stop use Pro DJ Link fader-start commands sent only to the selected player's IP, with all other player commands
set to leave unchanged. Players must have distinct numbers from 1 to 4. CDJ-3000 and XDJ-XZ are excluded because
the documented fader-start feature is unsupported there. Other models still need hardware validation.

For a quiet test, load a track on one player, set a cue, and try START, then STOP. Watch the
reported player state and the physical unit. A sent command is not an acknowledgement. If ignored, announce an unused
virtual player such as player 3 and retry. Do not use this first test during a performance.

Commands appear as `player_transport` events and as outgoing fader-start packets in Network with **The bench's own**
enabled. The setting is shared by clients of that bench and not persisted across restarts. A player that goes offline,
changes identity or has its number taken loses its switches until that clears. Switch Player control off when finished.

The same setting also enables **SYNC** and **MASTER**. These send a unicast command and wait for
normal status reports to show the result. They do not force a local display change or imply that hardware accepted it.
CDJ-3000 players may use these commands while their fader-start buttons remain disabled. The new commands need hardware
validation. Use them only when changing the setup's tempo ownership is safe.

## Status with every deck off

Players send their full status (playing, SYNC, MASTER, the bar) only to devices that announce themselves. Beats are
broadcast, so they come anyway. On a real network with every simulated deck off, the bench therefore announces itself
as an observer, the way `--observe` does, and the cards' lamps and the master's beat follow the players. It sends only
keep-alives: no status, beats or database. It stops when a deck is switched on, since that deck announces itself.

While **Read track info by itself** or **Read waveforms by itself** is on, its number is one from 1 to 4 that no
device uses, since older players answer those requests only from such a number (beat-link's virtual CDJ does the
same). It moves to another free one if a player takes it. It first listens for 5 seconds after the bench starts and
announces nothing, as a player claims its number before using it. Announced at once, it took 1 before it had heard
anyone: an XDJ-1000MK2 that was player 1 dropped its track, in emergency loop (E-8306 NO FILE) while playing and
ejected while paused. With both settings off, or no number free, it is 7, outside the players' range, at once.

The status line at the top of the page says which: **listening** and the seconds left, **on the link as player 2**
(or **number 7**), or **number 2 in use, silent** while another device has it. Its tooltip says why that number. The
state has it as `protocols.prolink.presence`.

## Observe without a simulated deck

```sh
python -m deckbench --phone --observe --dj-interface "Ethernet 2"
```

Use your platform's actual interface name. This announces an observer so players can send their full status,
but creates no playback cards, simulated mixer, database servers or outgoing beat/status stream. It is not passive
sniffing. Without `--observer-number`, its number is chosen as above. A number given is announced at once, so give
one that no device uses. A detected number conflict suppresses
observer announcements and raises a network warning. Announcements resume and the warning clears when the conflict ends.

**Read track info** queries the reported track's source player, not necessarily the player playing it. This is a
bounded, read-only request, separate from player control. Older players require an announced unused number 1 to 4,
which the bench's presence and `--observe` take by themselves, or an unused bench deck in that range that is on.
The query requires an analyzed track with a reported ID and an unambiguous online source. Missing artist or duration
fields remain unknown. Network audio, remote loading and waveform downloads are not provided by this query.
Firewall TCP rules for serving metadata are not needed for this outgoing query, though local security policies can
still restrict outbound TCP connections. The existing scoped inbound UDP rule remains necessary on Windows.

## Offline capture replay

### Recording a hardware issue

The Network view renders the latest 400 matching packets. Follow off holds those
rows for reading. Export view saves filtered browser history, or the held rows.
Export capture ignores those view filters and saves the server's retained UDP
packets, up to 12,000 statuses/beats/positions and 8,000 other packets. Both
buffers are bounded, so neither is a full-session recorder.

For an intermittent failure, add `--capture session.jsonl --events events.jsonl`
to the normal launch command. The capture file must not already exist. Recording
continues regardless of the selected browser tab, filters, Pause, Follow or Clear.
Stop the bench with Ctrl-C when finished. Long sessions can consume substantial
disk space. A capture write failure is reported in the terminal.

Use Mark in Network to note a physical button press, visible failure or recovery.
Markers go into Events, not UDP. Events and Network share a session identifier
and start time. Clearing Events does not reset the clock. Every external player's
reported state changes generate `player_state` events, without requiring a target.
Use `--target 2` or an IPv4 address only when unit-specific scenarios are needed.

This records packets the bench observes, not every packet on the switch. Incoming
database queries to the bench are also noted in Events. Unicast database or NFS
traffic between two physical players requires a mirrored switch port or a network
tap. Do not assume an ordinary PC capture can see it.

### Inspecting an export

New Network exports retain complete packet payloads. You can inspect them without sending anything to the DJ network:

```sh
python -m deckbench.capture capture.json --seed 42 --loss 5 --delay-ms 10 --jitter-ms 20
```

This feeds only the decoder, using a virtual clock. Seeded impairments make a run repeatable and can reorder arrivals.
The JSON result contains device state, packet counts and dropped-packet totals. It does not replay commands onto live
hardware or render a timed browser session. Older truncated exports are rejected. Keep real captures local, since they
can contain device identities and track information. Do not commit them.
JSON Lines recordings are accepted too. Offline decoding is bounded to 20,000
packets, 16 MiB of payload and a 40 MiB file. Trim a long recording to the relevant
window before replaying it, preserving complete JSON lines.
