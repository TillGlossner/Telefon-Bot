"""Testpaket; legt ``src`` auf den Importpfad, damit auch ``unittest`` laeuft."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Erwartete Warnungen der Engine sollen die Testausgabe nicht zumuellen.
import logging

logging.getLogger("telefonbot").setLevel(logging.CRITICAL)
