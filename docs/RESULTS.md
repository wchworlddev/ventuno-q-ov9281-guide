# Successful measurements

These results summarize the original successful CAMERA0 session on Ubuntu
`6.8.0-1084-qcom`. They are historical hardware measurements, not a claim
that the refactored helpers have completed a fresh hardware validation.
The compact source data is [successful-capture.json](../data/successful-capture.json).

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
