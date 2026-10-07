# Successful measurements

These results summarize the original successful CAMERA0 session on Ubuntu
`6.8.0-1084-qcom`. They are historical hardware measurements, not a claim
that the refactored helpers have completed a fresh hardware validation.
The compact source data is [successful-capture.json](../data/successful-capture.json).

The later automatic-startup measurements are separate, as recorded below.

| Measurement | Observed result |
| --- | --- |
| Image format | 1280 × 800, monochrome RAW8 / `GREY` |
| High-rate test | 143.9772 fps |
| Saved high-rate frames | 720 complete images |
| Payload per frame | 1,024,000 bytes |
| Sequence gaps | None observed |
| Mean frame interval | 6.9455 ms |
| Normal capture after restoration | Eight complete images at 27.4848 fps |
| Controls after restoration | Exact match to the saved normal controls |
| Driver ABI | 146 matching stock symbol CRC entries |
| Installed kernel/module replacement | None |

The high-rate runs lasted about five seconds. These results do not qualify
continuous capture, multi-camera operation or synchronization with a printer.
Frame rates were calculated from kernel monotonic EOF timestamps after
warm-up, with payload size and sequence continuity checked separately.

## Global shutter

OMNIVISION specifies OV9281 as a global shutter sensor. During the successful
test, sampled images of a moving rectangular card showed no obvious
rolling-shutter skew and were qualitatively consistent with that specification.
[Sensor manufacturer](https://www.ovt.com/products/ov9281/).

The motion was by hand, with perspective and lens distortion uncontrolled.
No pulsed-light experiment measured row exposure timing. External trigger
operation and trigger synchronization were not verified.

The vendor's Raspberry Pi guide also lists approximately 143.66 fps for
1280 × 800 RAW8 using built-in drivers. That is supporting context for the
chosen mode, not evidence of VENTUNO Q compatibility by itself.
[InnoMaker mode documentation](https://github.com/INNO-MAKER/CAM-OV9281RAW-V2/blob/main/readme.md).

## Automatic startup with the replacement ribbon

On October 7, 2026, the original VENTUNO Q and sensor captured real images
with a replacement ribbon. The working persistence implementation was then
checked through two ordinary reboots, using the normal controls above.

| Check | First reboot | Second reboot |
| --- | --- | --- |
| Camera startup service | Succeeded | Succeeded |
| Current boot configuration and health flag | Verified / cleared | Verified / cleared |
| Complete saved RAW8 frames | 8 | 8 |
| Payload per frame | 1,024,000 bytes | 1,024,000 bytes |
| Observed frame rate | 27.4652 fps | 27.4666 fps |
| Sequence gaps | 0 | 0 |
| Manual driver loading or camera configuration | None | None |
| Camera kernel Oops or sensor initialization error | None observed | None observed |

Both samples showed the real room scene. Streaming stopped afterward and
the sensor/capture controller returned to runtime suspend. The automatic
configuration does not enable high frame rate capture.

[Sanitized startup evidence](../data/startup-verification.json) contains the
measurements without photographs, addresses, passwords or private snapshots.
The public helpers refactor this working setup; their fresh-installation
workflow was not deployed again during the documentation cleanup.
Disconnected-camera boot, multi-camera capture and sustained reliability
remain untested. See [startup and recovery](STARTUP.md).
