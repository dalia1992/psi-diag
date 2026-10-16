"""Carga de claves desde un archivo .env (uso local). En Colab se usan los Secretos."""
import os
import pathlib

from dotenv import load_dotenv


def cargar_env(ruta=None) -> bool:
    """Carga el .env sin pisar variables ya definidas. Devuelve True si encontró el archivo.

    Orden de búsqueda: el argumento, la variable POC_ENV_FILE y el .env de la carpeta del proyecto.
    """
    candidata = ruta or os.getenv("POC_ENV_FILE") or pathlib.Path(__file__).resolve().parent.parent / ".env"
    candidata = pathlib.Path(candidata)
    if not candidata.is_file():
        return False
    load_dotenv(candidata, override=False)
    return True
