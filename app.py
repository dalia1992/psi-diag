# Punto de entrada que Vercel (y `uvicorn app:app`) buscan en la raíz del repositorio; el código real vive en backend/src/.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend" / "src"))

from servidor import app  # noqa: E402,F401
