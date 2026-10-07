# Primary sources

## Board and camera

- [Arduino VENTUNO Q documentation](https://docs.arduino.cc/hardware/ventuno-q/)
- [Arduino ABX00181 pinout](https://docs.arduino.cc/resources/pinouts/ABX00181-full-pinout.pdf)
- [Arduino ABX00181 schematic](https://docs.arduino.cc/resources/schematics/ABX00181-schematics.pdf)
- [InnoMaker CAM-OV9281RAW-V2 repository](https://github.com/INNO-MAKER/CAM-OV9281RAW-V2)
- [InnoMaker V2 manual](https://github.com/INNO-MAKER/CAM-OV9281RAW-V2/blob/main/CAM-OV9281RAW%20V2%20User%20Manual%20V1.4.pdf)
- [OMNIVISION OV9281 specification](https://www.ovt.com/products/ov9281/)

## Exact Ubuntu source

The supported build is `linux-qcom 6.8.0-1084.89`, corresponding to
`6.8.0-1084-qcom`. Its
[source descriptor](https://ports.ubuntu.com/ubuntu-ports/pool/universe/l/linux-qcom/linux-qcom_6.8.0-1084.89.dsc)
lists these archive checksums:

| Archive | SHA-256 |
| --- | --- |
| `linux-qcom_6.8.0.orig.tar.gz` | `26512115972bdf017a4ac826cc7d3e9b0ba397d4f85cd330e4e4ff54c78061c8` |
| `linux-qcom_6.8.0-1084.89.diff.gz` | `a9654afb1345e35236146a8afc7adf851868910fd4b890c313b6d9bdb1672960` |

The build helper obtains these archives from the same Ubuntu archive
directory, verifies their bytes, extracts the original CAMSS files and
applies only Ubuntu's CAMSS diff sections. It then applies this repository's
receiver patch. The unmodified rebuild must match the installed module's
source version and ABI before the corrected module is produced.

## Driver and API references

- [Upstream v6.8 OV9282/OV9281 driver](https://github.com/torvalds/linux/blob/v6.8/drivers/media/i2c/ov9282.c)
- [Upstream v6.8 Qualcomm CCI driver](https://github.com/torvalds/linux/blob/v6.8/drivers/i2c/busses/i2c-qcom-cci.c)
- [Qualcomm camera routing reference](https://github.com/qualcomm-linux/kernel-topics/commit/10a66404c1056d28d6f0e7bb3453ede44c79b58d)
- [Linux ARM EFI device-tree boot values](https://docs.kernel.org/arch/arm/uefi.html)
- [V4L2 memory mapping](https://docs.kernel.org/userspace-api/media/v4l/mmap.html)
- [V4L2 multi-planar API](https://docs.kernel.org/userspace-api/media/v4l/planar-apis.html)
- [V4L2 stream start/stop](https://docs.kernel.org/userspace-api/media/v4l/vidioc-streamon.html)
- [systemd v255 udev rule ordering and attribute matches](https://github.com/systemd/systemd/blob/v255/man/udev.xml)
- [systemd v255 udevadm verify and rule reload](https://github.com/systemd/systemd/blob/v255/man/udevadm.xml)

The reviewed board used systemd/udev 255. Its vendor video-discovery rule
had SHA-256 `d5a6c72c7c3a50e251f74c15672a47f63674aa12eda64086a7daffa49c4c55f8`.
The workaround uses a local same-name override, checksum checks and syntax
verification, without altering the packaged rule or triggering new events.

Compatibility fingerprints exclude per-board serial/MAC values and EFI
boot addresses. The boot candidate keeps the current board's values; it
does not restore another board's firmware snapshot.

The compiler's `graph_child_address` warning notes that address cells are
optional for a graph containing only port zero. This repository retains the
numbered port from the working layout and disables that one warning;
other compiler warnings and structural validation failures stop preparation.
[Linux v6.8 device-tree compiler check](https://github.com/torvalds/linux/blob/v6.8/scripts/dtc/checks.c).
