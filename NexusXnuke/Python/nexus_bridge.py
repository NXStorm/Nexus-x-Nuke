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
            "https://github.com/NXStorm/nex-gs-viewer/releases"
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

    tip = nuke.Text_Knob(
        "nexus_tip",
        "",
        "<i>Edit in NEXUS &rarr; clean/animate &rarr; viewer's '&rarr; Nuke' "
        "button &rarr; Import result</i>",
    )
    tip.setFlag(nuke.STARTLINE)
    node.addKnob(tip)
    return node
