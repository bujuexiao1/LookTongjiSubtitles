#!/usr/bin/env python3
"""Console helper entrypoint for the V2 desktop app."""

from __future__ import annotations

import os
import sys

from look_tongji_app_state import bundled_env, effective_env_path


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.environ.update(bundled_env(os.environ))
    os.environ["LOOK_TONGJI_ENV_PATH"] = str(effective_env_path())
    import look_tongji

    return int(look_tongji.main())


if __name__ == "__main__":
    raise SystemExit(main())
