# SPDX-License-Identifier: MIT
"""Discover CAMERA0, capture RAW8, and run a bounded 144 fps benchmark."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile

from .common import PLATFORM, ROOT, command, program, require, sensor_client, test_session
from .kernel import loaded_version

WIDTH, HEIGHT = 1280, 800
FRAME_SIZE = WIDTH * HEIGHT
CONTROLS = ('vertical_blanking', 'horizontal_blanking', 'exposure', 'analogue_gain',
            'horizontal_flip', 'vertical_flip')
NORMAL = dict(vertical_blanking=4000, horizontal_blanking=176, exposure=2500,
              analogue_gain=32, horizontal_flip=1, vertical_flip=1)


def discover():
    test_session()
    sensor_client()
    require(loaded_version() == PLATFORM['patched_srcversion'], 'Load the corrected CAMSS module first.')
    controllers = []
    for node in sorted(Path('/dev').glob('media*')):
        graph = command(program('media-ctl'), '-d', node, '-p')
        if re.search(r'^driver\s+qcom-camss$', graph, re.M):
            controllers.append((str(node), graph))
    require(len(controllers) == 1, 'Expected one CAMSS media controller.')
    media, graph = controllers[0]
    entities = {}
    for block in graph.split('\n- entity ')[1:]:
        match = re.match(r'\d+: (.*?) \(', block)
        if match:
            entities[match.group(1)] = block
    names = [name for name in entities if re.fullmatch(r'ov9281 \d+-0060', name)]
    require(len(names) == 1, 'Expected one OV9281 sensor in the capture graph.')
    name = names[0]
    require(re.search(r'-> "msm_csiphy0":0 \[ENABLED,IMMUTABLE\]', entities[name]), 'Sensor is not routed to CSIPHY0.')
    sensor = re.search(r'device node name (/dev/v4l-subdev\d+)', entities[name])
    video = re.search(r'device node name (/dev/video\d+)', entities.get('msm_vfe0_video0', ''))
    require(sensor and video, 'Sensor or VFE0 capture node is missing.')
    for entity in ('msm_csiphy0', 'msm_csid0', 'msm_vfe0_rdi0'):
        require(entity in entities, 'Missing pipeline entity: ' + entity)
    return {'media': media, 'sensor_entity': name, 'sensor_node': sensor.group(1), 'video': video.group(1)}


def controls(pipeline):
    text = command(program('v4l2-ctl'), '-d', pipeline['sensor_node'], '--get-ctrl=' + ','.join(CONTROLS))
    values = {key: int(value) for key, value in re.findall(r'^(\w+):\s*(-?\d+)', text, re.M)}
    require(set(values) == set(CONTROLS), 'Could not read all sensor controls.')
    return values


def set_controls(pipeline, values):
    require(set(values) <= set(CONTROLS), 'Unreviewed sensor control requested.')
    argument = ','.join(f'{key}={value}' for key, value in values.items())
    command(program('v4l2-ctl'), '-d', pipeline['sensor_node'], '--set-ctrl=' + argument)


def restore_controls(pipeline, saved):
    # Blanking must change before exposure: a combined ioctl can clamp the
    # exposure against the old, shorter frame-length limit.
    set_controls(pipeline, {key: saved[key] for key in CONTROLS[:2]})
    set_controls(pipeline, {key: saved[key] for key in CONTROLS[2:]})
    require(controls(pipeline) == saved, 'Sensor controls were not restored exactly.')


def configure(pipeline):
    media = program('media-ctl')
    command(media, '-d', pipeline['media'], '-l',
            '"msm_csiphy0":1 -> "msm_csid0":0 [1], "msm_csid0":1 -> "msm_vfe0_rdi0":0 [1]')
    pads = [(pipeline['sensor_entity'], 0), ('msm_csiphy0', 0), ('msm_csiphy0', 1),
            ('msm_csid0', 0), ('msm_csid0', 1), ('msm_vfe0_rdi0', 0), ('msm_vfe0_rdi0', 1)]
    command(media, '-d', pipeline['media'], '-V', ', '.join(
        f'"{entity}":{pad} [fmt:Y8_1X8/{WIDTH}x{HEIGHT} field:none]' for entity, pad in pads))
    command(program('v4l2-ctl'), '-d', pipeline['video'],
            f'--set-fmt-video=width={WIDTH},height={HEIGHT},pixelformat=GREY')
    text = command(program('v4l2-ctl'), '-d', pipeline['video'], '--get-fmt-video')
    require("'GREY'" in text and re.search(r'Width/Height\s+: 1280/800', text)
            and re.search(r'Bytes per Line\s+: 1280\b', text), 'Negotiated RAW8 format differs.')


def configure_normal():
    pipeline = discover()
    configure(pipeline)
    restore_controls(pipeline, NORMAL)
    return dict(pipeline, controls=controls(pipeline), configured=True, capture_started=False)


def result_directory(output):
    if output is None:
        output = ROOT / 'captures' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    return output


def stop(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=3)


def stream(pipeline, frames, warmup, output):
    require(shutil.disk_usage('/dev/shm').free > frames * FRAME_SIZE + 128 * 1024**2,
            'Insufficient /dev/shm space for this bounded capture.')
    temporary = Path(tempfile.mkdtemp(prefix='ov9281-guide-', dir='/dev/shm'))
    raw = temporary / 'capture.raw'
    process = None
    try:
        args = [program('timeout'), '--signal=INT', '--kill-after=3s', '12s', program('v4l2-ctl'),
                '-d', pipeline['video'], '--stream-mmap=16', f'--stream-count={frames}',
                f'--stream-skip={warmup}', '--stream-poll', f'--stream-to={raw}', '--verbose']
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        stdout, stderr = process.communicate(timeout=18)
        records = [(int(seq), int(size), float(ts)) for seq, size, ts in re.findall(
            r'cap dqbuf:.*?seq:\s*(\d+).*?bytesused:\s*(\d+).*?ts:\s*([0-9.]+)', stderr)]
        steady = records[warmup:]
        gaps = [[a[0], b[0]] for a, b in zip(records, records[1:]) if b[0] != a[0] + 1]
        size = raw.stat().st_size if raw.exists() else 0
        fps = ((len(steady) - 1) / (steady[-1][2] - steady[0][2])) if len(steady) > 1 and steady[-1][2] > steady[0][2] else None
        previews = []
        if size >= FRAME_SIZE:
            with raw.open('rb') as data:
                for index in sorted({0, min(frames - 1, size // FRAME_SIZE - 1)}):
                    data.seek(index * FRAME_SIZE)
                    frame = data.read(FRAME_SIZE)
                    require(len(frame) == FRAME_SIZE, 'Incomplete preview frame.')
                    name = f'frame-{index:04d}.pgm'
                    (output / name).write_bytes(b'P5\n1280 800\n255\n' + frame)
                    previews.append(name)
        success = process.returncode == 0 and size == frames * FRAME_SIZE and len(steady) == frames \
            and not gaps and all(row[1] == FRAME_SIZE for row in records)
        return {'success': success, 'exit_code': process.returncode, 'requested_frames': frames,
                'complete_saved_frames': size // FRAME_SIZE, 'trailing_bytes': size % FRAME_SIZE,
                'observed_fps': fps, 'sequence_gaps': gaps, 'previews': previews,
                'timestamp_basis': 'Kernel monotonic end-of-frame, not exposure-start',
                'stdout': stdout, 'stderr': stderr, 'bulk_raw_retained': False}
    finally:
        try:
            stop(process)
        finally:
            shutil.rmtree(temporary)


def capture(frames=8, output=None):
    require(1 <= frames <= 32, 'Normal capture accepts 1..32 frames.')
    pipeline = discover()
    configure(pipeline)
    restore_controls(pipeline, NORMAL)
    output = result_directory(output)
    report = dict(pipeline, width=WIDTH, height=HEIGHT, format='GREY / RAW8', controls=controls(pipeline))
    report.update(stream(pipeline, frames, 2, output))
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    require(report['success'], f'Capture did not complete: {output / "result.json"}')
    return dict(report, output=str(output))


def benchmark(frames=720, output=None):
    require(32 <= frames <= 720, 'The 144 fps benchmark accepts 32..720 frames (at most about five seconds).')
    pipeline = discover()
    # Configure the graph before the standard controls so changes in RAW
    # format cannot silently reset the control snapshot.
    configure(pipeline)
    saved = controls(pipeline)
    require(saved == NORMAL, 'Run configure or capture first to establish the reviewed normal settings.')
    require(shutil.disk_usage('/dev/shm').free > 1024**3, 'The benchmark needs over 1 GiB free in /dev/shm.')
    available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    require(available > 2 * 1024**2, 'The benchmark needs over 2 GiB available system RAM.')
    output = result_directory(output)
    report = dict(pipeline, width=WIDTH, height=HEIGHT, format='GREY / RAW8', saved_controls=saved)
    try:
        set_controls(pipeline, {'exposure': 150, 'analogue_gain': 224})
        set_controls(pipeline, {'vertical_blanking': 115})
        report['benchmark_controls'] = controls(pipeline)
        report.update(stream(pipeline, frames, 32, output))
    finally:
        try:
            restore_controls(pipeline, saved)
            report['restored_controls'] = controls(pipeline)
            report['controls_restored_exactly'] = report['restored_controls'] == saved
        finally:
            (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    require(report.get('success'), f'Benchmark did not complete: {output / "result.json"}')
    require(report['observed_fps'] is not None and 142 <= report['observed_fps'] <= 146,
            f'Frames arrived but measured rate differs from 144 fps: {output / "result.json"}')
    return dict(report, output=str(output))
