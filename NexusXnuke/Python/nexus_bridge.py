"""Nexus x Nuke — edit Gaussian Splats in NEXUS GS Viewer, straight from Nuke.

Workflow: pick a splat file (or grab it from the selected node), click
"Edit in NEXUS" to open it in the viewer, clean/animate there, hit the
viewer's "-> Nuke" button, then "Import result" here to load the edited
splats back as a GeoImport.
"""

import json
import os
import platform
import subprocess

import nuke

SPLAT_EXTS = (".ply", ".spz", ".splat", ".ksplat")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".nuke", "nexus_x_nuke.json")


# ---------------------------------------------------------------------------
# Settings (remembers the NEXUS executable path between sessions)
# ---------------------------------------------------------------------------
def _load_settings():
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def _save_settings(data):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except (IOError, OSError):
        pass


def _say(msg):
    """Message box in the GUI, plain print in terminal mode."""
    if nuke.GUI:
        nuke.message(msg)
    else:
        print("[NexusXnuke] " + msg)


# ---------------------------------------------------------------------------
# Locating the NEXUS GS Viewer executable
# ---------------------------------------------------------------------------
def find_nexus():
    """Best-effort search: saved setting, env var, then platform defaults."""
    saved = _load_settings().get("exe", "")
    if saved and os.path.exists(saved):
        return saved

    env = os.environ.get("NEXUS_GS_VIEWER", "")
    if env and os.path.exists(env):
        return env

    candidates = []
    system = platform.system()
    if system == "Windows":
        # The viewer registers its own path in HKCU on first launch.
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Classes\NEXGSViewer.splat\shell\open\command",
            )
            cmd = winreg.QueryValue(key, None)
            winreg.CloseKey(key)
            exe = cmd.split('"')[1] if cmd.startswith('"') else cmd.split(" %")[0]
            candidates.append(exe)
        except OSError:
            pass
    elif system == "Darwin":
        candidates += [
            "/Applications/NEXUS GS Viewer.app/Contents/MacOS/NEXUS GS Viewer",
            os.path.expanduser(
                "~/Applications/NEXUS GS Viewer.app/Contents/MacOS/NEXUS GS Viewer"
            ),
        ]
    else:
        candidates += [
            "/opt/nexus-gs-viewer/nexus-gs-viewer",
            os.path.expanduser("~/NEXUS GS Viewer-linux-x64/nexus-gs-viewer"),
        ]

    for c in candidates:
        if c and os.path.exists(c):
            return c
    return ""


# ---------------------------------------------------------------------------
# Node actions
# ---------------------------------------------------------------------------
def _default_output(src):
    root, _ = os.path.splitext(src)
    return root + "_nexus.ply"


def grab_from_selection(node):
    """Fill the GS file knob from the selected node's file-type knobs."""
    try:
        sel = nuke.selectedNode()
    except ValueError:
        sel = None
    if sel is None or sel is node:
        _say("Select a node that reads a splat file (GeoImport, ReadGeo...) first.")
        return
    for knob in sel.allKnobs():
        if isinstance(knob, nuke.File_Knob):
            value = knob.value() or ""
            if value.lower().endswith(SPLAT_EXTS):
                node["gs_file"].setValue(value)
                if not node["gs_out"].value():
                    node["gs_out"].setValue(_default_output(value))
                return
    _say("No splat file (.ply/.spz/.splat/.ksplat) found on '%s'." % sel.name())


def edit_in_nexus(node):
    """Launch NEXUS GS Viewer on the source file with a round-trip target."""
    exe = node["nexus_exe"].value() or find_nexus()
    if not exe or not os.path.exists(exe):
        _say(
            "NEXUS GS Viewer not found.\n\nSet the 'NEXUS app' knob to the "
            "executable, or install the viewer:\n"
            "https://github.com/NXStorm/nexus-gs-viewer/releases"
        )
        return

    src = node["gs_file"].evaluate() or node["gs_file"].value()
    if not src or not os.path.exists(src):
        _say("Set 'GS file' to an existing splat file first (or use Grab from selected).")
        return

    out = node["gs_out"].value() or _default_output(src)
    node["gs_out"].setValue(out.replace("\\", "/"))
    node["nexus_exe"].setValue(exe.replace("\\", "/"))
    _save_settings({"exe": exe})

    kwargs = {}
    if platform.system() == "Windows":
        # Detached: closing Nuke must not kill the viewer, and vice versa.
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([exe, src, "--roundtrip", out], **kwargs)
    nuke.tprint(
        "[NexusXnuke] Editing %s in NEXUS — click the viewer's '-> Nuke' button, "
        "then 'Import result' here." % os.path.basename(src)
    )


def import_result(node):
    """Load the edited splats back into the scene as a GeoImport."""
    out = node["gs_out"].evaluate() or node["gs_out"].value()
    if not out or not os.path.exists(out):
        _say(
            "No edited file yet.\n\nIn NEXUS, click the '-> Nuke' button to "
            "export the cleaned scene, then try again."
        )
        return None

    geo = None
    for node_class in ("GeoImport", "ReadGeo2"):
        try:
            geo = nuke.createNode(node_class, inpanel=False)
            break
        except RuntimeError:
            continue
    if geo is None:
        _say("Could not create a GeoImport/ReadGeo node in this Nuke version.")
        return None

    geo["file"].setValue(out.replace("\\", "/"))
    geo.setName("NexusResult")
    geo.setXYpos(node.xpos() + 120, node.ypos() + 60)
    nuke.tprint("[NexusXnuke] Imported %s (%s)" % (out, geo.Class()))
    if nuke.GUI:
        nuke.message(
            "Imported into '%s'.\n\nSelect it, press V to view, then Tab to "
            "enter the 3D viewport." % geo.name()
        )
    return geo


# ---------------------------------------------------------------------------
# Camera round-trip
# ---------------------------------------------------------------------------
def _chan_path(node):
    out = node["gs_out"].value() or _default_output(node["gs_file"].value() or "scene.ply")
    return os.path.splitext(out)[0] + ".chan"


def import_camera(node):
    """Create an animated Nuke Camera from the .chan the viewer exported.

    The viewer writes it next to the round-trip file when you click its
    '-> Nuke' button with at least 2 camera keys on the timeline.
    """
    chan = _chan_path(node)
    if not os.path.exists(chan):
        _say(
            "No camera file yet (%s).\n\nIn NEXUS, set at least 2 camera keys "
            "on the timeline, then click the '-> Nuke' button." % os.path.basename(chan)
        )
        return None

    rows = []
    with open(chan, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 7:
                rows.append([float(v) for v in parts])
    if len(rows) < 2:
        _say("Camera file looks empty or invalid: %s" % chan)
        return None

    cam = None
    for node_class in ("Camera4", "Camera3", "Camera2", "Camera"):
        try:
            cam = nuke.createNode(node_class, inpanel=False)
            break
        except RuntimeError:
            continue
    if cam is None:
        _say("Could not create a Camera node in this Nuke version.")
        return None

    cam.setName("NexusCamera")
    cam.setXYpos(node.xpos() - 120, node.ypos() + 60)
    if "rot_order" in cam.knobs():
        cam["rot_order"].setValue("ZXY")  # ordre d'écriture du .chan NEXUS

    for knob_name in ("translate", "rotate"):
        cam[knob_name].setAnimated()
    has_focal = "focal" in cam.knobs()
    if has_focal:
        cam["focal"].setAnimated()

    for row in rows:
        frame = int(row[0])
        for axis in range(3):
            cam["translate"].setValueAt(row[1 + axis], frame, axis)
            cam["rotate"].setValueAt(row[4 + axis], frame, axis)
        if has_focal and len(row) >= 8:
            cam["focal"].setValueAt(row[7], frame)

    nuke.tprint("[NexusXnuke] Camera imported: %d frames from %s" % (len(rows), chan))
    if nuke.GUI:
        nuke.message(
            "Camera imported into '%s' (%d frames, ZXY, focal for the default "
            "24.576 mm horizontal aperture)." % (cam.name(), len(rows))
        )
    return cam


def send_camera(node):
    """Export the selected Nuke Camera as .chan and replay it in the viewer."""
    try:
        cam = nuke.selectedNode()
    except ValueError:
        cam = None
    if cam is None or not cam.Class().startswith("Camera"):
        _say("Select a Camera node first.")
        return

    if "rot_order" in cam.knobs() and cam["rot_order"].value() != "ZXY":
        _say(
            "The camera's rotation order is '%s'. NEXUS expects ZXY — set the "
            "Camera's rot order to ZXY (values unchanged for pan/tilt-only "
            "moves) and try again." % cam["rot_order"].value()
        )
        return

    src = node["gs_file"].evaluate() or node["gs_file"].value()
    if not src or not os.path.exists(src):
        _say("Set 'GS file' to an existing splat file first.")
        return

    root = nuke.root()
    first = int(root["first_frame"].value())
    last = int(root["last_frame"].value())
    fps = int(root["fps"].value() or 25)

    chan = os.path.splitext(src)[0] + "_nukecam.chan"
    has_focal = "focal" in cam.knobs()
    with open(chan, "w") as f:
        for frame in range(first, last + 1):
            values = [frame - first + 1]
            for axis in range(3):
                values.append(cam["translate"].getValueAt(frame, axis))
            for axis in range(3):
                values.append(cam["rotate"].getValueAt(frame, axis))
            values.append(cam["focal"].getValueAt(frame) if has_focal else 50.0)
            f.write(" ".join("%.6f" % v if i else str(int(v)) for i, v in enumerate(values)) + "\n")

    exe = node["nexus_exe"].value() or find_nexus()
    if not exe or not os.path.exists(exe):
        _say("Camera written to %s, but NEXUS GS Viewer was not found." % chan)
        return

    out = node["gs_out"].value() or _default_output(src)
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [exe, src, "--roundtrip", out, "--chan", chan, "--fps", str(fps)], **kwargs
    )
    nuke.tprint(
        "[NexusXnuke] Camera '%s' sent (%d frames @ %d fps) — replaying on %s in NEXUS."
        % (cam.name(), last - first + 1, fps, os.path.basename(src))
    )


# ---------------------------------------------------------------------------
# Headless playblast
# ---------------------------------------------------------------------------
def playblast(node):
    """Render a playblast through the viewer's headless CLI and Read it back.

    Uses the scene's saved animation (sidecar) if present, otherwise an
    automatic orbit.
    """
    exe = node["nexus_exe"].value() or find_nexus()
    src = node["gs_file"].evaluate() or node["gs_file"].value()
    if not exe or not os.path.exists(exe):
        _say("NEXUS GS Viewer not found — set the 'NEXUS app' knob.")
        return
    if not src or not os.path.exists(src):
        _say("Set 'GS file' to an existing splat file first.")
        return

    out = os.path.splitext(src)[0] + "_playblast.mp4"
    if os.path.exists(out):
        os.remove(out)
    fps = int(nuke.root()["fps"].value() or 30)

    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [exe, src, "--render", out, "--res", "1920x1080", "--fps", str(fps)], **kwargs
    )
    nuke.tprint("[NexusXnuke] Playblast rendering to %s ..." % out)

    def _finish():
        read = nuke.createNode("Read", inpanel=False)
        read["file"].setValue(out.replace("\\", "/"))
        read.setName("NexusPlayblast")
        read.setXYpos(node.xpos() + 240, node.ypos() + 60)
        nuke.tprint("[NexusXnuke] Playblast imported: %s" % out)

    def _wait(timeout=600):
        import time

        size = -1
        for _ in range(timeout):
            time.sleep(1)
            if os.path.exists(out):
                new_size = os.path.getsize(out)
                if new_size > 0 and new_size == size:
                    return True  # taille stable = rendu terminé
                size = new_size
        return False

    if nuke.GUI:
        import threading

        def _bg():
            if _wait():
                nuke.executeInMainThread(_finish)
            else:
                nuke.executeInMainThread(
                    lambda: nuke.message("Playblast timed out — check the viewer log.")
                )

        threading.Thread(target=_bg, daemon=True).start()
        _say("Playblast rendering in the background — a Read node will appear when done.")
    else:
        if _wait():
            _finish()
        else:
            _say("Playblast timed out.")
    return out


# ---------------------------------------------------------------------------
# Node creation
# ---------------------------------------------------------------------------
def create_node():
    node = nuke.createNode("NoOp", inpanel=True)
    node.setName("NexusEdit")
    node["tile_color"].setValue(0xFFB454FF)  # NEXUS amber

    node.addKnob(nuke.Tab_Knob("nexus_tab", "NEXUS"))

    gs_file = nuke.File_Knob("gs_file", "GS file")
    node.addKnob(gs_file)
    node.addKnob(
        nuke.PyScript_Knob(
            "nexus_grab",
            "Grab from selected",
            "import nexus_bridge; nexus_bridge.grab_from_selection(nuke.thisNode())",
        )
    )

    gs_out = nuke.File_Knob("gs_out", "Edited output")
    node.addKnob(gs_out)

    exe = nuke.File_Knob("nexus_exe", "NEXUS app")
    exe.setValue(find_nexus().replace("\\", "/"))
    node.addKnob(exe)

    edit = nuke.PyScript_Knob(
        "nexus_edit",
        "  Edit in NEXUS  ",
        "import nexus_bridge; nexus_bridge.edit_in_nexus(nuke.thisNode())",
    )
    edit.setFlag(nuke.STARTLINE)
    node.addKnob(edit)
    node.addKnob(
        nuke.PyScript_Knob(
            "nexus_import",
            "  Import result  ",
            "import nexus_bridge; nexus_bridge.import_result(nuke.thisNode())",
        )
    )

    cam_import = nuke.PyScript_Knob(
        "nexus_cam_import",
        "  Import camera  ",
        "import nexus_bridge; nexus_bridge.import_camera(nuke.thisNode())",
    )
    cam_import.setFlag(nuke.STARTLINE)
    node.addKnob(cam_import)
    node.addKnob(
        nuke.PyScript_Knob(
            "nexus_cam_send",
            "  Send camera  ",
            "import nexus_bridge; nexus_bridge.send_camera(nuke.thisNode())",
        )
    )
    node.addKnob(
        nuke.PyScript_Knob(
            "nexus_playblast",
            "  Playblast  ",
            "import nexus_bridge; nexus_bridge.playblast(nuke.thisNode())",
        )
    )

    tip = nuke.Text_Knob(
        "nexus_tip",
        "",
        "<i>Edit in NEXUS &rarr; clean/animate &rarr; viewer's '&rarr; Nuke' "
        "button &rarr; Import result</i>",
    )
    tip.setFlag(nuke.STARTLINE)
    node.addKnob(tip)
    return node
