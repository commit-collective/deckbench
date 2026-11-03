# DeckBench on macOS

Native interface selection and MAC discovery are implemented using the system's read-only `/sbin/ifconfig -a` output.
No runtime package or root access is needed by DeckBench. Physical Mac compatibility is still awaiting validation.
The dedicated Mac CI job is configured for native unicast, browser and packaging checks, not hardware certification.

## Real players

Use Python 3.8 or later from a terminal in the checkout. `python3` is commonly the command on a Mac.

1. Connect Ethernet to the DJ switch. Wi-Fi may remain connected for internet and phone access
2. Identify the wired interface and its configured IPv4 address

```sh
python3 -m deckbench --network-info
```

Interface names are usually `en0`, `en7` or similar, not the friendly service name in System Settings. Do not assume
`en0` is Ethernet. The listing also shows loopback-free IPv4 candidates and their masks. No configuration is changed.

Choose an unused player number and use the interface shown, replacing `en7` in these examples:

```sh
# Observe without a simulated playback deck
python3 -m deckbench --observe --dj-interface en7

# Or run one simulated player, initially off
python3 -m deckbench --numbers 3 --dj-interface en7
```

Run one command at a time. Open `http://127.0.0.1:8750/`, then enable the virtual player if using the second command.
It must not share a player number with the hardware. Leave the simulated mixer off when a physical DJM is present.
For metadata requests to older players, use an unused number 1 to 4, such as `--observe --observer-number 3`.

If macOS asks for local-network or incoming-connection access for your terminal or Python, allow that application
for this test. Do not disable the firewall globally. An isolated DJ connection must use the players' subnet without
replacing your normal connection's default route. See [real-network.md](real-network.md) for addressing and phone access.

Start with one player using the adapter's existing address. Multiple simulated players need additional configured
IPv4 addresses. The selector refuses mixed-subnet or insufficient-address configurations rather than changing them.
Advanced aliases can use /32 masks on macOS, so select those with explicit `--bind ADDRESS,... --netmask LAN-MASK`
and `--broadcast LAN-BROADCAST` instead of expecting `--dj-interface` to infer their parent subnet.
Any manually created aliases need explicit cleanup by their owner. DeckBench never creates or removes them.

## Local software and virtual machines

The default `127.0.0.N` broadcast bench is not a supported native Mac topology. Adding loopback aliases alone does not
make Linux-style loopback broadcasts work. Keep DeckBench and the software under test on the same broadcast-capable segment:

- A VM's host-only bridge can provide an isolated segment without real DJ hardware
- A bridged Ethernet interface can put applications, virtual machines and real players on the same segment
- Default user-mode NAT and TCP port forwarding do not provide this discovery path

Run DeckBench with `--dj-interface` set to the Mac interface on that segment, such as `bridge100` or `en7`. The host
and guest must have different addresses on the same subnet. Use the interface's actual IPv4 address and mask rather
than assuming a particular vmnet address range.

For a native application, configure it to use the same interface. For a virtual machine, use the virtualization
software's documented host-only or bridged networking setup. DeckBench does not create or manage virtual networks.
Check that UDP discovery and replies can travel in both directions, not just that a TCP port is reachable.

Encapsulated Ethernet-over-UDP segments are not native Pro DJ Link UDP. Pointing `--broadcast` at a multicast group
does not add support for an arbitrary tunnel format. Such transports need a compatible bridge or adapter.
These are network requirements, not a claim of validated compatibility with every application or hypervisor.

Alternatively, run DeckBench and the client inside the same Linux VM using the Linux loopback bench. That remains
distinct from running DeckBench natively on macOS.

## Acceptance checklist

- Confirm `--network-info` lists the correct wired or VM bridge address and mask
- Start one observer and confirm discovered names, playback status and beats
- Start an unused virtual player and check discovery from the hardware or emulator
- Check SYNC tempo following and MASTER handoff in both directions
- Stop with Ctrl+C, restart and confirm ports were released
- Record Mac version, Intel or Apple Silicon, Python version, interface and emulator network mode

Export a short Network capture if a step fails. Keep captures and pairing tokens private.
