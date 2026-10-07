# Automatic CAMERA0 startup

The original board implementation passed two ordinary reboots on October 7,
2026. On both boots the sensor bound, the corrected CAMSS module loaded, the
media pipeline was configured automatically, and a capture produced eight
complete 1280×800 RAW8 frames at 27.47 fps without manual configuration.
[Sanitized measurements](../data/startup-verification.json).

The public helpers refactor that working logic into the tutorial. Their
complete installation workflow has not been rerun on fresh hardware. Keep
the existing working board installation when using this tutorial as reference.

## Fresh setup using the guide

First follow README steps 1–6: build the checked driver, prepare one camera
boot, load the driver and complete a normal capture. The installer requires
a successful normal capture from the current boot, a matching driver build,
and the normal control values. Close camera applications before installing.

```bash
sudo python3 camera.py enable-startup
sudo reboot
```

Installation copies the checked module, build record and Python helpers to
root-owned `/usr/local/lib/ov9281-guide`. Boot no longer depends on the user
checkout. It creates `ov9281-guide-camera.service` and a kernel-update hook,
then appends a managed entry to the existing optional GRUB camera menu.
The main GRUB file, stock module, kernel and initrd are preserved.

The installer starts no stream and performs no reboot itself. The selected
camera must remain connected to CAMERA0 before the next boot.

## Verify startup

```bash
cd ~/ventuno-q-ov9281-guide
sudo python3 camera.py startup-status
python3 camera.py capture-ready --frames 8
```

Expected startup status:

- Service: `ActiveState=active`, `SubState=exited`, `Result=success`.
- `last_startup.boot_id` matches `/proc/sys/kernel/random/boot_id`.
- `configuration_verified` and `boot_health_flag_cleared` are true.
- `ov9281_guide_pending=0`, `ov9281_guide_disabled=0`.

Expected capture: eight complete images, no trailing bytes or sequence gaps,
and `configuration_changed: false`. Inspect a PGM preview to confirm the real
scene. An ordinary `capture` command configures the camera again, so use
`capture-ready` to check what startup actually configured.

Repeat an ordinary reboot and `capture-ready` for a second startup check.
This is a short functional check, not a long-duration reliability qualification.

The service configures 1280×800 `GREY`/RAW8 using blanking 4000, exposure
2500 and gain 32. It leaves streaming stopped. The optional 144 fps benchmark
remains a separate command and restores normal controls when it finishes.

## Discovery workaround

Automatic module loading exposed a kernel initialization race: `v4l_id`
opened a newly registered CAMSS capture node while some VFE entities still
had uninitialized pads. The fault was in `camss_find_sensor`, reached through
the video-open power/clock path. Waiting for udev afterward cannot prevent
an open that happens during registration.

The helper installs `/etc/udev/rules.d/60-persistent-v4l.rules`, copying the
checksum-reviewed Ubuntu rule and changing only the `v4l_id` import for node
names matching `msm_vfe*_video*`. Other nodes retain ordinary discovery, and
the remaining vendor rules are preserved. It verifies rule syntax and reloads
rules without triggering device events.

The original `/usr/lib/udev/rules.d/60-persistent-v4l.rules` remains intact.
Ubuntu gives a same-name `/etc` rule priority over its vendor counterpart.
[systemd v255 rule documentation](https://github.com/systemd/systemd/blob/v255/man/udev.xml).

The guide records both rule hashes under `/boot/ov9281-guide/discovery.json`
and saves the vendor rule there for audit. If an Ubuntu update changes the
vendor rule, the helpers stop for review. `cleanup-boot` removes only the
recorded override, revealing Ubuntu's current vendor rule.

## Recovery and removing the camera

GRUB sets `ov9281_guide_pending=1` before a camera boot. Successful startup
clears it. A startup failure keeps it set, so the next ordinary restart uses
stock Ubuntu. This flag selects the next boot; it cannot recover a running
kernel that has already hung. If the kernel faults, avoid forced module
unloading. Try an ordinary reboot and use the local console if recovery stalls.

Before intentionally removing the camera, disable startup:

```bash
sudo python3 camera.py disable-startup
sudo poweroff
```

**Unplug the supply before touching the ribbon.** Shutdown alone can leave
connector power present. After removal, the next boot uses stock Ubuntu.

If the camera is removed without disabling startup, the expected first boot
is Ubuntu with a failed camera service, followed by stock Ubuntu on the next
restart. A disconnected-camera boot was not physically tested during this work.

To reconnect, shut down, unplug power, attach CAMERA0, and boot stock Ubuntu.
Then re-enable the existing setup and restart:

```bash
sudo python3 camera.py enable-startup
sudo reboot
```

A kernel post-install hook disables camera startup when a different kernel
is installed. Do not force re-enable or reuse the old module on a new kernel.
Review the port, rebuild against that kernel, and repeat capture verification.
Changed boot files may also require manual review before cleanup.

## Full removal

From the checkout, with camera applications closed:

```bash
sudo python3 camera.py remove-startup
sudo python3 camera.py cleanup-boot
sudo reboot
```

Removal verifies owned files, restores the original one-time camera menu,
removes the startup service/hook/assets, then removes the temporary boot
files and discovery override. It does not unload the running driver. The
restart restores stock Ubuntu's device tree and installed drivers.

## The board already configured during this work

That working installation uses the earlier paths and flags below. It was
left intact during the tutorial refactor. Do not run the fresh guide's
`prepare-boot` or `enable-startup` over it; preflight rejects the existing port.

Check it:

```bash
systemctl status ov9281-camera.service --no-pager
python3 /usr/local/lib/ov9281-camera/manage.py --status
```

The existing manager reports `last_configuration`, with the current boot ID,
`configuration_verified: true`, `boot_health_flag_cleared: true`, and
`ov9281_pending=0`, `ov9281_disabled=0`.

Before removing its camera:

```bash
sudo grub-editenv /boot/grub/grubenv set ov9281_disabled=1 ov9281_pending=1
sudo poweroff
```

Unplug power before removing or reconnecting the ribbon. After reconnecting
CAMERA0 and booting stock Ubuntu, re-enable this existing installation with:

```bash
sudo python3 /usr/local/lib/ov9281-camera/manage.py --select-cameras 0
sudo reboot
```

To remove that earlier installation, undo its discovery override first:

```bash
sudo python3 /usr/local/lib/ov9281-camera/udev-startup-workaround.py --undo
sudo python3 /usr/local/lib/ov9281-camera/manage.py --remove
sudo reboot
```

The private usage record, helpers and verification reports remain on that
board in `~/ov9281-new-ribbon-20261007/`. This public repository contains
source and sanitized measurements, without private boot snapshots or images.
