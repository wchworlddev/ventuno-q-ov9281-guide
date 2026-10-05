# SPDX-License-Identifier: MIT
"""Build the reviewed camera overlay and reject unrelated FDT changes."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess

from .common import ROOT, PLATFORM, program, require, sha256


def read_fdt(path):
    """Read v17 FDT properties and reservations for a semantic comparison."""
    data = Path(path).read_bytes()
    if len(data) < 40:
        raise ValueError("Truncated FDT header")
    magic, total, tree, strings, reserve, version, _, cpu, slen, tlen = struct.unpack_from(
        ">10I", data
    )
    if magic != 0xD00DFEED or version < 17 or total > len(data):
        raise ValueError("Expected a complete v17 FDT")
    if tree + tlen > total or strings + slen > total:
        raise ValueError("FDT block lies outside the blob")
    reservations = []
    cursor = reserve
    while True:
        if cursor + 16 > total:
            raise ValueError("Truncated reservation map")
        address, size = struct.unpack_from(">QQ", data, cursor)
        cursor += 16
        if address == size == 0:
            break
        reservations.append([address, size])
    properties = {}
    stack = []
    cursor = tree
    while cursor < tree + tlen:
        token = struct.unpack_from(">I", data, cursor)[0]
        cursor += 4
        if token == 1:
            end = data.index(b"\0", cursor, tree + tlen)
            stack.append(data[cursor:end].decode())
            cursor = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, offset = struct.unpack_from(">II", data, cursor)
            cursor += 8
            start = strings + offset
            end = data.index(b"\0", start, strings + slen)
            name = data[start:end].decode()
            key = "/" + "/".join(stack[1:] + [name])
            if key in properties or cursor + length > tree + tlen:
                raise ValueError("Invalid or duplicate FDT property")
            properties[key] = data[cursor:cursor + length]
            cursor = (cursor + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError("Unbalanced FDT nodes")
            return properties, reservations, cpu
        else:
            raise ValueError(f"Unknown FDT token {token}")
    raise ValueError("FDT has no end marker")


def cells(*values):
    return struct.pack(">" + "I" * len(values), *values)

def build_candidate(base, output):
    base, output = Path(base), Path(output)
    dtc, fdtoverlay = program('dtc'), program('fdtoverlay')
    overlay = ROOT / 'overlays/camera0-ov9281.dtso'
    require(sha256(overlay) == PLATFORM['overlay_sha256'], 'Reviewed overlay source differs.')
    before, reservations, cpu = read_fdt(base)
    require(b"arduino,monza\0" in before.get("/compatible", b""),
            "Base is not the inspected VENTUNO Q board")
    require(before.get("/soc@0/#address-cells") == cells(2)
            and before.get("/soc@0/#size-cells") == cells(2), "Unexpected SoC address layout")
    for symbol in ("camss", "camcc", "intc", "vreg_l4a", "vreg_l5a", "cci0_0_default", "cci0_0_sleep"):
        require("/__symbols__/" + symbol in before, "Missing symbol: " + symbol)
    require(not any(k.startswith("/soc@0/cci@ac13000/") for k in before),
            "CCI0 already exists; review instead of merging automatically")
    require(any(k.startswith("/soc@0/qcom,cci0@ac13000/") for k in before),
            "Expected downstream CCI0 placeholder is missing")
    camss = before["/__symbols__/camss"].rstrip(b"\0").decode()
    require(before.get(camss + "/compatible") == b"qcom,qcs8300-camss\0",
            "Unexpected capture interface")
    require(before.get(camss + "/status") == b"disabled\0", "CAMSS already enabled")
    require(not any(k.startswith(camss + "/ports/port@0/endpoint") for k in before),
            "Camera0 already has an endpoint")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    dtbo = output / "camera0-ov9281.dtbo"
    candidate = output / "camera0-ov9281-candidate.dtb"
    # Keep the tested numbered CAMERA0 port. Kernel dtc warns that the
    # address cells are optional with one port; its layout is valid and is
    # checked below. Keep every other compiler warning fatal.
    commands = [
        [dtc, "-Wno-graph_child_address", "-@", "-I", "dts", "-O", "dtb", "-o", str(dtbo), str(overlay)],
        [fdtoverlay, "-i", str(base), "-o", str(candidate), str(dtbo)],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
        require(not result.stderr, "Device-tree tool reported warnings: " + result.stderr)
    after, new_reservations, new_cpu = read_fdt(candidate)
    require(reservations == new_reservations and cpu == new_cpu, "FDT reservation/header changed")
    allowed_prefixes = ("/soc@0/cci@ac13000/", "/clocks/ov9281-camera0-clock/",
                        camss + "/ports/port@0/endpoint/")
    allowed_properties = {camss + "/status", camss + "/vdda-phy-supply", camss + "/vdda-pll-supply",
                          "/soc@0/qcom,cci0@ac13000/status"}
    delta = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        allowed = key in allowed_properties or key.startswith(allowed_prefixes)
        allowed |= key.startswith("/__symbols__/ov9281_") and old is None
        require(allowed, "Unexpected property change: " + key)
        require(new is not None, "Property was deleted: " + key)
        delta.append({"property": key, "before_hex": old.hex() if old is not None else None,
                      "after_hex": new.hex()})
    sensor = "/soc@0/cci@ac13000/i2c-bus@0/sensor@60"
    sensor_ep = sensor + "/port/endpoint"
    receiver_ep = camss + "/ports/port@0/endpoint"
    require(after[sensor_ep + "/remote-endpoint"] == after[receiver_ep + "/phandle"]
            and after[receiver_ep + "/remote-endpoint"] == after[sensor_ep + "/phandle"],
            "Camera endpoint links are not reciprocal")
    require(after[sensor_ep + "/data-lanes"] == cells(1, 2), "Unexpected sensor lane mapping")
    require(after[receiver_ep + "/data-lanes"] == cells(0, 1), "Unexpected receiver lane mapping")
    require(after[sensor_ep + "/link-frequencies"] == struct.pack(">Q", 400000000),
            "Unexpected sensor link frequency")
    require(not any(k.startswith(sensor + "/") and k.endswith("gpios") for k in after),
            "Sensor would drive a GPIO")
    report = {"status": "offline_candidate",
              "hardware_capture_verified": False, "boot_verified": False,
              "base_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
              "overlay_source_sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
              "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
              "reservation_map_preserved": True, "unrelated_properties_unchanged": True,
              "sensor_gpio_assigned": False, "property_changes": delta}
    (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
