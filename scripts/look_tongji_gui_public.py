#!/usr/bin/env python3
"""Public launcher for the Tongji subtitle GUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["LOOK_TONGJI_APP_VARIANT"] = "public"

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import look_tongji_gui


if __name__ == "__main__":
    look_tongji_gui.main()
