# SPDX-License-Identifier: MIT OR Apache-2.0
"""Matching what the device under test is (its state) against what a scenario expects.

`match` is a dict of key: wanted. A wanted value is

  a plain value                    equal to it
  {"near": 128, "tol": 0.5}        a number within `tol` (default 0.5) of it
  {"min": 100, "max": 140}         a number in that range (either end may be left out)
  {"in": [1, 2]}                   one of them
  {"not": 3}                       anything but it (a plain value or another of these)

A key the state has not got never matches, except under "not".
"""


def matches_value(value, want):
    if isinstance(want, dict):
        try:
            if "near" in want:
                return abs(float(value) - float(want["near"])) <= float(want.get("tol", 0.5))
            if "in" in want:
                return value in want["in"]
            if "not" in want:
                return not matches_value(value, want["not"])
            if "min" in want or "max" in want:
                number = float(value)
                return number >= float(want.get("min", float("-inf"))) and number <= float(want.get("max", float("inf")))
        except (TypeError, ValueError):
            return False
        return False
    return value == want


def matches(state, match):
    """True if every key of `match` is satisfied by `state`."""
    for key, want in match.items():
        if key not in state:
            if not (isinstance(want, dict) and "not" in want):
                return False
            continue
        if not matches_value(state[key], want):
            return False
    return True


def explain(state, match):
    """What is not as wanted, in words: 'master is False (wanted True), bpm is 126.0 (wanted near 128 +-0.5)'."""
    out = []
    for key, want in match.items():
        if key in state and matches_value(state[key], want):
            continue
        if isinstance(want, dict):
            parts = []
            if "near" in want:
                parts.append("near %s +-%s" % (want["near"], want.get("tol", 0.5)))
            if "in" in want:
                parts.append("one of %s" % (want["in"],))
            if "not" in want:
                parts.append("not %s" % (want["not"],))
            if "min" in want or "max" in want:
                parts.append("from %s to %s" % (want.get("min", "-"), want.get("max", "-")))
            wanted = ", ".join(parts)
        else:
            wanted = str(want)
        out.append("%s is %s (wanted %s)" % (key, state[key] if key in state else "not known", wanted))
    return ", ".join(out)
