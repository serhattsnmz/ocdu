"""PyInstaller entry point for the standalone ocdu executable."""

from __future__ import annotations

from ocdu.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
