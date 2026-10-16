"""`.vercelignore` no debe dejar fuera nada que la función necesite en ejecución."""
import ast
import fnmatch
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTAS_DE_EJECUCION = (
    "app.py", "componentes.py", "errores_api.py", "vercel.json", "requirements.txt", ".python-version",
    "poc_psico/grafo.py", "poc_psico/ocr.py", "exportar/docx.py", "exportar/pdf.py", "exportar/comun.py",
    "models/ner", "assets/fonts", "public/index.html", "public/app.js",
)


def _patrones() -> list:
    lineas = (RAIZ / ".vercelignore").read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lineas if l.strip() and not l.strip().startswith("#")]


def _coincide(ruta: str, patron: str) -> bool:
    """Lógica sencilla tipo .gitignore: «/x» ancla en la raíz, «x/» es carpeta, sin «/» coincide con cualquier nombre."""
    anclado, solo_carpeta = patron.startswith("/"), patron.endswith("/")
    patron = patron.strip("/")
    partes = ruta.split("/")
    if anclado or "/" in patron:
        n = len(patron.split("/"))
        if len(partes) < n or (solo_carpeta and len(partes) == n):
            return False
        return fnmatch.fnmatchcase("/".join(partes[:n]), patron)
    nombres = partes[:-1] if solo_carpeta else partes
    return any(fnmatch.fnmatchcase(nombre, patron) for nombre in nombres)


def _ignorada(ruta: str) -> bool:
    return any(_coincide(ruta, p) for p in _patrones() if not p.startswith("!"))


def test_vercelignore_excluye_lo_que_no_hace_falta_en_ejecucion():
    for ruta in ("tests/test_api.py", "docs/superpowers/plan.md", "scripts/probar_caso.py", ".superpowers/sdd/x.md",
                 "README.md", "DESPLIEGUE.md", "poc_psico/__pycache__/x.pyc", ".pytest_cache/v", "requirements-dev.txt"):
        assert _ignorada(ruta), ruta


def test_vercelignore_no_excluye_nada_de_lo_que_la_funcion_usa():
    existentes = []
    for base in RUTAS_DE_EJECUCION:
        destino = RAIZ / base
        assert destino.exists(), base
        existentes += [str(p.relative_to(RAIZ)) for p in ([destino] if destino.is_file() else destino.rglob("*")) if p.is_file()]
    assert existentes
    for ruta in existentes:
        assert not _ignorada(ruta), f".vercelignore deja fuera {ruta}"


def _modulos_locales(archivo: Path) -> set:
    """Módulos del proyecto importados en el archivo, incluidas las importaciones diferidas dentro de funciones."""
    locales = {p.stem for p in RAIZ.glob("*.py")} | {p.name for p in RAIZ.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    encontrados = set()
    for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres = [a.name for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            nombres = [nodo.module] + [f"{nodo.module}.{a.name}" for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 1:
            base = archivo.relative_to(RAIZ).parent.as_posix().replace("/", ".")
            nombres = [f"{base}.{nodo.module}" if nodo.module else base] + [f"{base}.{a.name}" for a in nodo.names]
        else:
            continue
        encontrados |= {n for n in nombres if n.split(".")[0] in locales}
    return encontrados


def test_todo_modulo_importado_en_ejecucion_existe_y_no_esta_ignorado():
    pendientes = [RAIZ / "app.py", RAIZ / "componentes.py"]
    vistos, revisados = set(), 0
    while pendientes:
        archivo = pendientes.pop()
        if archivo in vistos:
            continue
        vistos.add(archivo)
        for modulo in _modulos_locales(archivo):
            ruta = RAIZ / Path(*modulo.split("."))
            if ruta.with_suffix(".py").is_file():
                destino = ruta.with_suffix(".py")
            elif (ruta / "__init__.py").is_file():
                destino = ruta / "__init__.py"
            elif ruta.parent.with_suffix(".py").is_file() or (ruta.parent / "__init__.py").is_file():
                continue   # «from paquete.modulo import nombre»: el nombre no es un módulo
            else:
                raise AssertionError(f"{archivo.name} importa {modulo}, que no existe")
            assert not _ignorada(destino.relative_to(RAIZ).as_posix()), f"{modulo} está en .vercelignore"
            revisados += 1
            pendientes.append(destino)
    assert revisados >= 15   # app, componentes, errores_api, poc_psico/* y exportar/*
