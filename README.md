# OV9281 on Arduino VENTUNO Q with Ubuntu

A source guide to the **successful CAMERA0 bring-up and automatic startup** of an InnoMaker
CAM-MIPI9281RAW-V2 monochrome camera on VENTUNO Q. The sensor is **OV9281**;
“OV9821” is a name mix-up. This port uses Ubuntu's `ov9282` sensor driver,
which also supports OV9281, and a two-line correction to Qualcomm CAMSS.

The original setup captured 1280 × 800 RAW8 images at **143.98 fps** in a
short test, then restored normal settings and captured eight more images
at approximately **27.5 fps**. See [successful results](docs/RESULTS.md).

With a replacement ribbon, CAMERA0 also initialized automatically on two
ordinary reboots and captured eight complete RAW8 frames after each, at
**27.47 fps**, without manual driver loading or camera configuration.
The startup discovery workaround and recovery procedure are covered in
[automatic startup](docs/STARTUP.md).

## Supported setup

| Item | Configuration used |
| --- | --- |
| Board | Arduino VENTUNO Q / QCS8300 |
| OS | Ubuntu 24.04.5 LTS, AArch64 |
| Kernel | `6.8.0-1084-qcom` |
| Ubuntu kernel source | `linux-qcom 6.8.0-1084.89` |
| Camera | InnoMaker CAM-MIPI9281RAW-V2 / OV9281 |
| Connector | **CAMERA0**, one connected camera |
| Capture | 1280 × 800, `GREY` / RAW8, two CSI-2 lanes |

The compatibility checks are intentionally scoped to this Ubuntu build.
A different kernel, firmware hardware layout or GRUB layout requires a new
review and module build. Do not bypass a failed check or force a module load.

The measurements are from the working board implementation. These helpers
are its refactored, source-only version, including the subsequently verified
startup logic. The complete refactored workflow has **not been rerun on a
fresh board**. Compatibility checks stop on an unfamiliar layout.

If the camera is already working with `/usr/local/lib/ov9281-camera/manage.py`,
use the [existing-installation instructions](docs/STARTUP.md#the-board-already-configured-during-this-work).
Do not run a second installer over that setup.

## 1. Connect the camera

Shut down and **unplug the board's power supply** before touching the ribbon.
Connect the camera to the connector printed CAMERA0 with the appropriate
VENTUNO Q 22-pin to camera 15-pin CSI ribbon. Verify the electrical pinout,
contact orientation and both latches using the
[Arduino pinout](https://docs.arduino.cc/resources/pinouts/ABX00181-full-pinout.pdf)
and [InnoMaker manual](https://github.com/INNO-MAKER/CAM-OV9281RAW-V2/blob/main/CAM-OV9281RAW%20V2%20User%20Manual%20V1.4.pdf).
The cable must fit without forcing it. Remove the lens cap and light the scene.

Boot stock Ubuntu. Keep a keyboard and monitor available for boot recovery.

## 2. Install build and capture tools

Run these commands **on the VENTUNO Q**, as your normal Ubuntu user:

```bash
uname -r
sudo apt-get install git python3 build-essential gcc-13 binutils zstd patch \
  device-tree-compiler v4l-utils linux-headers-6.8.0-1084-qcom
git clone https://github.com/wchworlddev/ventuno-q-ov9281-guide.git
cd ventuno-q-ov9281-guide
```

`uname -r` must show `6.8.0-1084-qcom`. The build requires GCC 13.3.0 and the
matching headers. If the exact headers are unavailable from your configured
Ubuntu repositories, stop rather than substituting a different kernel.
The prerequisite command installs tools and headers; it does not replace
the running kernel or install the patched capture driver. Standard Ubuntu
`systemd`, `udevadm`, `kmod` and GRUB utilities must also be available.

## 3. Build the temporary CAMSS correction

```bash
python3 camera.py build-driver
```

This downloads about 250 MB of checksum-pinned Ubuntu source into `build/`,
extracts the CAMSS subsystem, and applies Ubuntu's subsystem changes. It
builds an **unpatched** module first and checks its source version and exact
ELF symbol-version section against the installed module. It then applies
[the two-line patch](patches/qcs8300-csiphy.patch) and checks the patched ABI,
dependencies and kernel compatibility string again.

Outputs are `build/qcom-camss-ov9281.ko` and `build/driver.json`. Nothing is
installed into `/lib/modules`. Build as a normal user, without sudo.

## 4. Select one camera boot

```bash
sudo python3 camera.py prepare-boot
```

The helper checks the kernel, hardware fingerprint, stock module, GRUB
layout and environment. It builds a candidate from **this board's firmware
device tree** and verifies that only the reviewed camera properties change.
It preserves the main GRUB menu, kernel, initrd and default Ubuntu entry.
It creates an optional CAMERA0 entry and selects it for **one boot only**.
Before the camera boot, it installs a checked local video-discovery rule
that avoids premature `v4l_id` opens of CAMSS nodes. Ubuntu's original rule
is preserved; `cleanup-boot` removes this guide's override.

Only when the command reports `selected_for_one_boot: true`, run:

```bash
sudo reboot
```

An ordinary restart after the test returns to stock Ubuntu. If the test
entry hangs, restarting the board should select stock Ubuntu because GRUB
consumes the one-time selection before booting the test kernel.

## 5. Load the temporary capture driver

After the test boot:

```bash
cd ~/ventuno-q-ov9281-guide
sudo python3 camera.py load
python3 camera.py plan
```

The sensor must already be bound to `ov9282`. If sensor initialization fails,
stop here; the capture steps require a responding sensor. The loader checks
the build record and uses ordinary module operations. It reloads stock
dependencies before `insmod`, avoiding the missing DMA dependency encountered
during the original bring-up. It verifies the discovery guard and refuses
driver operations after a kernel Oops. It does not replace the installed
Ubuntu module or start a stream.

The original unsigned module was used with Secure Boot disabled and kernel
lockdown inactive. The helper does not change either setting. A locked-down
or signature-enforcing kernel may reject an unsigned build.

`plan` discovers the actual media, sensor and video nodes. Their numbers can
change between boots; do not assume `/dev/video0` or a fixed subdevice number.

## 6. Capture real images

```bash
python3 camera.py capture --frames 8
```

The command connects the media pipeline, sets 1280 × 800 RAW8, applies the
normal manual controls, and captures eight frames. It saves two unmodified
PGM grayscale previews and `result.json` in a new directory under `captures/`.
Open a `.pgm` file in an image viewer to inspect the actual scene.

Successful output includes `success: true`, eight complete saved frames,
zero trailing bytes and no sequence gaps. Bulk raw data is temporary and is
deleted after streaming stops. Capture commands normally run without sudo;
your account must have access to the media/video devices, typically through
Ubuntu's `video` group and desktop session permissions.

The tested normal controls are:

```text
vertical_blanking=4000   horizontal_blanking=176
exposure=2500           analogue_gain=32
horizontal_flip=1       vertical_flip=1
```

These are V4L2 control values, not microseconds. Exposure remains manual;
adjustments for a different scene require separate application work.

## 7. Optional short 144 fps test

First complete a normal capture, then run:

```bash
python3 camera.py benchmark-144 --frames 720
python3 camera.py capture --frames 8
```

The benchmark temporarily sets `exposure=150`, `analogue_gain=224` and
`vertical_blanking=115`, retaining RAW8 and `horizontal_blanking=176`.
It captures at most 720 frames, around five seconds, after 32 warm-up frames.
It needs over 1 GiB free in `/dev/shm` and over 2 GiB available RAM.

The capture process has a timeout. Bulk raw data is deleted, and the saved
normal controls are restored in `finally`, including interruption and failure
paths. Blanking is restored **before** exposure to avoid exposure clamping.
The final normal capture checks that the camera still works after the test.
Hard termination or power loss cannot execute Python cleanup. A restart
after a one-time test returns to stock Ubuntu. If automatic startup is
enabled, a successful restart reapplies the normal camera controls.

The original 144 fps result was a short measurement, not a qualification of
continuous operation. The moving-card images were consistent with the
manufacturer's global shutter specification; external triggering and
quantitative row-exposure timing were not measured.

## 8. Optional automatic startup

After a successful normal capture in the current one-time boot:

```bash
sudo python3 camera.py enable-startup
sudo reboot
```

After reboot:

```bash
cd ~/ventuno-q-ov9281-guide
sudo python3 camera.py startup-status
python3 camera.py capture-ready --frames 8
```

`capture-ready` reads the startup configuration and captures without changing
links, formats or controls. Check `success: true`, eight complete frames and
no sequence gaps, then repeat an ordinary reboot and this capture check.
Inspect a saved PGM to confirm it shows the actual scene.

Startup uses the normal ~27.5 fps settings. It does not start streaming or
enable the 144 fps benchmark. A failed startup leaves the next boot set to
stock Ubuntu; a kernel update disables automatic camera boot pending review.
See [startup, recovery, and camera removal](docs/STARTUP.md) for details.

## 9. Remove the boot setup

If automatic startup was installed, remove it first:

```bash
sudo python3 camera.py remove-startup
```

Then remove the temporary boot entry and discovery override:

```bash
sudo python3 camera.py cleanup-boot
sudo reboot
```

Cleanup verifies ownership of the guide's recorded menu before removing the
optional entry, discovery override and staged device tree. It leaves the active session alone;
the restart restores the stock device tree and installed drivers. Keep the
checkout and local build/capture outputs only if you want to reuse them.

To repeat a one-time test before installing automatic startup, use `sudo python3 camera.py repeat-boot`,
then `sudo reboot`. To restore just the stock capture module within an idle
test session, use `sudo python3 camera.py restore-driver`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `camera.py` | Single command-line entry point |
| `ov9281/` | Shared build, boot, discovery, startup and capture helpers |
| `overlays/` | Reviewed CAMERA0 overlay source |
| `patches/` | CAMSS QCS8300 receiver correction |
| `data/` | Compatibility fingerprints and sanitized successful measurements |
| `docs/` | Port explanation, results and primary sources |

Generated binaries, firmware blobs, captures and local logs are ignored by
Git. The guide covers the demonstrated single CAMERA0 setup. Simultaneous
CAMERA1/2 capture is not implemented or qualified. The public evidence is
sanitized measurement data; captured room photographs and private logs are
kept outside the repository.

## Further reading

- [How the port works](docs/PORTING.md)
- [Successful capture measurements](docs/RESULTS.md)
- [Automatic startup and recovery](docs/STARTUP.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Primary sources and pinned source archives](docs/SOURCES.md)

Original helper code and documentation are MIT licensed. The overlay retains
its BSD-3-Clause attribution, and the Linux driver patch is GPL-2.0-only.
See [LICENSE](LICENSE) and [third-party notices](NOTICE.md).
