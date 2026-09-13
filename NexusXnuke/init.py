# NEXUS Splats for Nuke — plugin path registration.
import nuke
import os

nuke.pluginAddPath(os.path.join(os.path.dirname(__file__), "Python"))
