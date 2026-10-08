"""Keep GUI tests offscreen and isolate all device and keyboard effects."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
