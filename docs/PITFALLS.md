# Pitfalls — Nexus x Nuke

The non-obvious traps met while building and running the plugin, and what to do about them. One entry per trap:
**symptom** → **cause** → **what to do**, with the file concerned. All paths are relative to the plugin folder
(`NexusXnuke/`); the code lives in `Python/nexus_bridge.py`.

## Install

- **The folder is in `~/.nuke` but no menu appears.** → Nuke runs `init.py` / `menu.py` only from directories on its
  plugin path, and there are two levels: your own `~/.nuke/init.py` must `nuke.pluginAddPath("./NexusXnuke")`, and the
  plugin's bundled `init.py` then adds `NexusXnuke/Python`. The menu icon resolves for the same reason. → Do both
  steps of the README; check `nuke.pluginPath()` from the Script Editor.
- **After an update the node still behaves like the old version (missing Import camera / Send camera / Playblast).**
  → A stale `Python/__pycache__/*.pyc` next to the source is loaded instead of the `.py` when Python considers it
  fresh. → Delete `__pycache__` inside the installed plugin folder after every update, and never ship one.
- **`nuke -t`: the NexusXnuke menu does not exist.** → Terminal mode executes `init.py` only, never `menu.py`.
  → `import nexus_bridge; nexus_bridge.create_node()` is the headless entry point.
- **The remembered viewer path is not saved.** → Settings go to `~/.nuke/nexus_x_nuke.json` and a failed write is
  swallowed; on a fresh machine `~/.nuke` may not exist yet. → Create `~/.nuke` (or launch Nuke once) before
  relying on the memory; the `NEXUS_GS_VIEWER` environment variable and the **NEXUS app** knob always win.
- **The viewer is found on Windows without any setting.** → The plugin reads the file association the viewer registers
  per user on its first launch (`HKCU\Software\Classes\<viewer progid>\shell\open\command`). → Launch the viewer once
  by hand after installing it, or set the knob.

## Nuke versions

- **`Camera4` / `GeoImport` do not exist on an older Nuke.** → Class names changed: Camera4 from Nuke 16, Camera3
  before, Camera2 earlier; `GeoImport` is the USD 3D system (15+), `ReadGeo2` the classic one. → The plugin probes
  newest-first (`for node_class in ("Camera4", "Camera3", …)`); keep that pattern for any new node type.
- **A second NEXUS Edit node errors on creation.** → `setName("NexusEdit")` without `uncollide=True` collides with the
  first one. → Pass `uncollide=True` when naming nodes.

## Camera round-trip (`.chan`)

- **The imported camera is off by a few degrees.** → The `.chan` written by the viewer is in Nuke's **ZXY** rotation
  order; the node sets `rot_order = ZXY` on import, and refuses to send a camera whose order is different. → Do not
  change the rotation order of the imported camera; convert your own camera to ZXY before sending (only value-preserving
  for pan/tilt-only moves).
- **The field of view does not match the viewer's playblast.** → The focal in the `.chan` is computed for Nuke's default
  **horizontal aperture of 24.576 mm**; a Camera whose `haperture` was changed by a template or a format preset gets
  a different FOV. → Keep the default aperture on the imported camera, or set `haperture` back to 24.576 (and
  `vaperture` to `24.576 × height / width`).
- **Sending then re-importing a camera shifts the animation.** → *Send camera* rebases the keys to frame 1; *Import
  camera* writes the keys at the frame numbers found in the file. On a 1001-based script the move comes back at 1..N.
  → Offset the imported curves by `first_frame − 1`, or start the script at frame 1 for round-trips.
- **NTSC rates replay at the wrong speed.** → `fps` is sent as an integer: 23.976 becomes 23, 29.97 becomes 29.
  → Use integer frame rates for camera exchanges, or match the viewer's timeline fps by hand.
- **A parented camera exports the wrong path.** → *Send camera* samples the camera's own `translate` / `rotate` knobs,
  not its world matrix. → Bake the world transform onto an unparented Camera before sending.
- **Two `.chan` files with similar names.** → Import reads `<edited file>.chan` (written by the viewer); Send writes
  `<source file>_nukecam.chan` so it never clobbers the viewer's export. Both are expected.

## The viewer process

- **The viewer's own messages never reach Nuke's console.** → The viewer is started detached (`DETACHED_PROCESS |
  CREATE_NEW_PROCESS_GROUP` on Windows, a new session elsewhere) so that closing Nuke does not kill it; its stdout is
  not captured. → Look at the viewer's own window and logs, not at Nuke.
- **Playblast: the imported MP4 is truncated.** → The node considers the render finished when the output file's size
  stops changing for one poll; a long stall in the encoder can end the wait early. → Wait for the viewer to close,
  then reload the Read (or run the playblast again).
- **Playblast: `PermissionError` on the second run (Windows).** → The previous run's `NexusPlayblast` Read still holds
  the MP4 open while the node deletes it. → Delete or disconnect the old Read first.
- **Playblast comes out at 1920×1080 regardless of the project format.** → The resolution is fixed in the launch
  command (`--res 1920x1080`); the fps is taken from the script root. → Change the constant if another size is
  needed; the viewer accepts any even size.
- **Launching from Nuke while the viewer is already open loses the arguments.** → The viewer relays a second launch to
  its running instance and the arguments are reordered on the way; only the `--flag=value` form survives that relay.
  → Close the viewer before launching a new round-trip, or keep flags in the `=` form when editing the launch line.

## Tests

- **Nothing can be imported outside Nuke.** → `nexus_bridge.py` imports `nuke` at module level. → Test inside Nuke
  (`nuke -t` and a script that imports the module), or move any pure helper you add into a Nuke-free module.
