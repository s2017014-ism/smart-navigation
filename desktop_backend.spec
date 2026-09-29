from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


root = Path.cwd()
data_files = [
    (str(path), "backend/data")
    for path in (root / "backend" / "data").glob("*.json")
]
data_files.extend(
    [(str(root / "data" / "macau_network.graphml"), "data")]
    if (root / "data" / "macau_network.graphml").exists()
    else []
)
hidden_imports = [
    "backend.main",
    "backend.graph_builder",
    "backend.places",
    "backend.router",
    "backend.transit",
]
for package in ("fastapi", "uvicorn", "networkx", "httpx", "pydantic"):
    hidden_imports.extend(collect_submodules(package))

analysis = Analysis(
    ["desktop_backend.py"],
    pathex=[str(root)],
    binaries=[],
    datas=data_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["osmnx"],
    noarchive=False,
    optimize=0,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="smart-navigation-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="smart-navigation-backend",
)
