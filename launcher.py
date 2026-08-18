"""Entry script for PyInstaller and for the Windows logon entry.

Works from a source checkout too: it puts ``src/`` on ``sys.path`` when the
package is not installed, so the autostart command stays a plain
``pythonw.exe launcher.py``.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from climitwatch.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
