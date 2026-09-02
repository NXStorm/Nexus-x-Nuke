# Nexus x Nuke — menu entries.
import nuke

toolbar = nuke.menu("Nodes")
menu = toolbar.addMenu("NexusXnuke", icon="NexusLogo.png")
menu.addCommand(
    "NEXUS Edit",
    "import nexus_bridge; nexus_bridge.create_node()",
    icon="NexusLogo.png",
)
