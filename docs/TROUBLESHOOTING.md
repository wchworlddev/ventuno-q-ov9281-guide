# Troubleshooting

## A compatibility check stops

Read the named check before changing anything. This guide targets one exact
Ubuntu/QCS8300 configuration. Different GRUB state, an existing camera port,
a changed discovery rule or a different kernel is a reason to review the
setup. Do not clear unrelated boot selections, overwrite another installation,
or bypass the hashes to make an installer proceed.

## Sensor initialization or Input/output error

The sensor must bind to `ov9282` before capture. An I²C write failure or
`Input/output error` means initialization did not complete; enabling CAMSS
or changing frame rate cannot repair that missing sensor connection.

Shut down and unplug power before inspecting the CAMERA0 ribbon, electrical
pinout, contact orientation and latches. A ribbon that passes DC continuity
can still fail CSI signal integrity. The replacement 22-to-15-pin ribbon
restored successful captures on the original board, making the old ribbon
or its contacts a strong suspect. That result does not isolate one physical
fault in every intermittent initialization failure.

## Unknown symbol while loading the module

Use `camera.py load`, which checks the exact build metadata and reloads the
stock module dependency list before `insmod`. Do not use forced module load
or bypass ABI/symbol-version checks.

## CAMSS remains busy

Close capture applications and browser camera tabs. Device discovery can
briefly hold a module reference; the helper waits for discovery and a zero
reference count. Do not force removal of a busy driver.

## Kernel Oops during startup

The reviewed boot workaround prevents `v4l_id` from opening CAMSS capture
nodes during incomplete registration. Check that the owned discovery rule
still matches its recorded hash. The helpers refuse further load/unload
operations after a kernel fault. Use recovery as described in
[STARTUP.md](STARTUP.md#recovery-and-removing-the-camera).

The startup fix addresses an observed software race. An earlier failed I²C
write alone is not evidence of that race or proof of hardware damage.

## Frames are dark or the benchmark rate differs

Check the lens cap and lighting. Normal exposure is manual. The 144 fps
test uses much shorter exposure and can need more light. Inspect the saved
PGMs and result JSON, including payload size, sequence continuity and EOF
timestamps. A short high-rate capture does not qualify sustained operation.

The tutorial's verified high-rate result is from VENTUNO Q, not from the
separate Raspberry Pi cross-check. Automatic startup uses the normal rate.
