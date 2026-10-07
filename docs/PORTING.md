# How the CAMERA0 port works

## Sensor support

Ubuntu's `ov9282` module matches `ovti,ov9281` and checks sensor chip ID
`0x9281`. The working camera used this existing sensor driver. It exposes
RAW8/RAW10 formats, exposure, gain, blanking and image flips through V4L2.
The source used for this work is the exact Ubuntu `linux-qcom` build named
in [SOURCES.md](SOURCES.md), rather than a current upstream driver substituted
into an older kernel.

## Firmware device tree

The reviewed stock firmware disables CAMSS and contains a downstream CCI0
placeholder. [The overlay](../overlays/camera0-ov9281.dtso):

1. Represents the camera module's 24 MHz oscillator with a fixed clock.
2. Adds a mainline-compatible CCI0 controller at `0x0ac13000`, using the
   reviewed camera clocks, interrupt and CAMERA0 pinctrl groups.
3. Declares one `ovti,ov9281` sensor at I²C address `0x60`.
4. Connects its two CSI-2 lanes to CAMSS CSIPHY0 with reciprocal endpoints.
5. Enables CAMSS and its PHY/PLL supplies, and disables the downstream CCI0
   placeholder to prevent a competing controller.

The sensor endpoints use data lanes `<1 2>`; the Qualcomm receiver endpoint
uses `<0 1>`. These are the mappings used in the working connector setup.
The represented link frequency is 400 MHz.

The InnoMaker module receives connector power and has its own clock and
regulators. The vendor manual marks camera connector pins 11 and 12
unconnected. This overlay assigns no sensor reset or enable GPIO and does
not repurpose the board's power pins. Missing named sensor supplies cause
the kernel to use dummy regulators, which was also seen during successful
capture; that message alone is not a capture failure.

The firmware FDT is obtained from `/sys/firmware/fdt`. Reconstructing a blob
from the sysfs property directories can lose reservation/header information
and is not used for booting. Preparation validates the FDT reservation map,
boot CPU and every changed property. It also checks endpoint reciprocity,
lane mapping, link frequency and the absence of assigned sensor GPIOs.

The kernel does not support applying this overlay live in the tested setup,
so GRUB supplies the candidate device tree for one boot. No replacement
kernel or initrd is required. The downstream `camera_qcs8300`,
`camera_qcs9100` and `camera_qcm6490` modules are blacklisted for that boot
to avoid competing camera stacks.

## The two-line CAMSS correction

The sensor and media graph initially registered, and the internal test-pattern
generator could send frames through the VFE capture path. Real sensor frames
did not arrive with the stock receiver initialization.

In Ubuntu's `camss-csiphy-3ph-1-0.c`, QCS8300 needs the existing SA8775P/gen2
initialization path. The patch adds `case CAMSS_8300:` to two switches:

- The PHY lane-register initialization selection.
- The existing gen2 initialization selection.

It introduces no sensor timing table, PLL setting, raw I²C access or new GPIO
assignment. The rebuilt module is checked against the stock module before
it is loaded. The original build matched all 146 symbol CRC entries and
the stock kernel compatibility string.

An unused dependency can disappear when `modprobe -r qcom-camss` removes
the stock driver. Since `insmod` does not resolve dependencies, the helper
reloads the stock dependency list first, then inserts the correction.

## Device discovery during registration

The exact Ubuntu CAMSS source registers VFE video nodes one line at a time.
Opening an early node powers the VFE and queries sensor pixel clocks for
other lines. Before all entities have pads, `camss_find_sensor` can
dereference an uninitialized pad array. This matches the later observed
startup fault in `v4l_id` through the CAMSS video-open path.

The discovery helper prevents the automatic identification program from
opening `msm_vfe*_video*` nodes during registration. It retains Ubuntu's
discovery logic for other nodes. Waiting for `udevadm settle` afterward is
still useful for reference counts, but cannot prevent an earlier open.
See [the checked workaround](STARTUP.md#discovery-workaround).

The same discovery, module loading and camera configuration helpers are
used by the temporary session and the automatic boot service. The service
does not start a stream. `capture-ready` verifies what the service configured
without applying links, formats or controls again.

## Media graph and frame timing

The working RAW8 route is:

```text
OV9281 → CSIPHY0 → CSID0 → VFE0 RDI0 → VFE0 video node
```

Every sensor/receiver pad is configured to `Y8_1X8/1280x800`, while the video
node uses `GREY`, 1280-byte stride and 1,024,000 bytes per image. Subdevice and
video numbers are discovered from `media-ctl`, rather than saved device names.

The short high-rate test uses the existing V4L2 vertical-blanking control.
Normal settings use blanking 4000, exposure 2500 and gain 32. The 144 fps
test uses blanking 115, exposure 150 and gain 224. The shorter exposure keeps
the image within the shorter frame period. No sensor PLL overclock was used.

Control restoration is ordered: blanking first, then exposure/gain/flips.
Restoring all values in one ioctl previously clamped exposure against the
old short frame-length limit. The refactored helper retains the corrected
two-call restoration order and reads back all controls.

## Using C++ applications

Once the sensor, patched receiver and media graph are configured, an
application can capture directly through the discovered V4L2 video node.
The per-frame path does not require Python. Start from `camera.py plan` and
`camera.py configure` rather than a fixed `/dev/videoN` number.

The observed node uses `V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE` with one RAW8
plane. A native application should negotiate that type, request and map
buffers, queue them, start streaming, dequeue/requeue frames, and always
stop streaming and release buffers on exit. Use kernel sequence numbers
and timestamps to measure frame delivery. Do not treat EOF timestamps as
exposure-start or trigger timestamps.

For the API contract, see the Linux documentation for
[memory-mapped capture](https://docs.kernel.org/userspace-api/media/v4l/mmap.html),
[the multi-planar API](https://docs.kernel.org/userspace-api/media/v4l/planar-apis.html),
and [stream control](https://docs.kernel.org/userspace-api/media/v4l/vidioc-streamon.html).
The successful evidence in this repository comes from `v4l2-ctl`; a separate
C++ capture implementation has not been benchmarked here.
