#!/usr/bin/env python3
"""Keep manually uploaded GLBs in modelos/ registered in catalogo.json.

Use --strip before the STEP converter so its legacy cleanup does not remove
manual GLBs. Run without arguments after STEP/orientation processing to validate
and add direct GLBs back to the catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "modelos"
CATALOG = ROOT / "catalogo.json"
CONFIG = ROOT / "config.json"

# Reuse the exact same GLB parser/validator as the STEP pipeline.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from converter import inspect_glb  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_catalog() -> dict:
    if not CATALOG.exists():
        return {"schema_version": 1, "models": []}
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("catalogo.json inválido")
    data.setdefault("schema_version", 1)
    return data


def save_catalog(data: dict) -> None:
    CATALOG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def strip_direct_entries() -> None:
    """Remove only catalog rows for direct GLBs, never the GLB files themselves."""
    catalog = load_catalog()
    before = len(catalog["models"])
    catalog["models"] = [
        model for model in catalog["models"]
        if model.get("import_type") != "direct_glb"
    ]
    removed = before - len(catalog["models"])
    if removed:
        save_catalog(catalog)
    print(f"GLB DIRETO: {removed} entrada(s) retirada(s) temporariamente do catálogo.")


def direct_id(relative: str) -> str:
    stem = Path(relative).stem
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:60] or "modelo"
    return "glb-" + slug + "-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:10]


def sync_direct_entries() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    catalog = load_catalog()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    max_bytes = int(float(config.get("max_output_mb", 25)) * 1024**2)
    max_instances = int(config.get("max_mesh_instances", 1000))
    max_triangles = int(config.get("max_triangles", 2_000_000))

    # Files already owned by the STEP converter are not direct uploads.
    generated_files = {
        str(model.get("file", ""))
        for model in catalog["models"]
        if model.get("source") and str(model.get("source")).lower().endswith((".step", ".stp"))
    }

    # Preserve any existing direct metadata when this script is run without --strip.
    previous_direct = {
        model.get("file"): model
        for model in catalog["models"]
        if model.get("import_type") == "direct_glb" and model.get("file")
    }
    catalog["models"] = [
        model for model in catalog["models"]
        if model.get("import_type") != "direct_glb"
    ]

    added = []
    warnings = []
    for path in sorted(MODELS_DIR.rglob("*.glb"), key=lambda p: p.as_posix().lower()):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in generated_files:
            continue

        try:
            stats = inspect_glb(path)
        except Exception as exc:
            msg = f"{relative}: GLB ignorado porque é inválido: {exc}"
            print(f"::warning title=GLB direto inválido::{msg}")
            warnings.append(msg)
            continue

        if stats["bytes"] > max_bytes:
            msg = (
                f"{relative}: {stats['bytes'] / 1024**2:.1f} MB excede o limite remoto "
                f"de {max_bytes / 1024**2:.0f} MB; não será listado no game."
            )
            print(f"::warning title=GLB direto grande demais::{msg}")
            warnings.append(msg)
            continue

        old = previous_direct.get(relative, {})
        entry = {
            "id": old.get("id") or direct_id(relative),
            "name": old.get("name") or path.stem,
            "author": old.get("author", ""),
            "description": old.get("description", "GLB enviado diretamente para a biblioteca."),
            "source": relative,
            "file": relative,
            **stats,
            "optimization": "prebuilt",
            "import_type": "direct_glb",
            "sha256": sha256(path),
        }
        complexity = []
        if stats["mesh_instances"] > max_instances:
            complexity.append(
                f"{stats['mesh_instances']} peças excedem o recomendado de {max_instances}."
            )
        if stats["triangles"] > max_triangles:
            complexity.append(
                f"{stats['triangles']:,} triângulos excedem o recomendado de {max_triangles:,}."
            )
        if complexity:
            entry["complexity_warnings"] = complexity
            for warning in complexity:
                print(f"::warning title=GLB direto pesado::{path.name}: {warning}")

        catalog["models"].append(entry)
        added.append(entry)
        print(
            f"GLB DIRETO {relative}: {stats['mesh_instances']} peças · "
            f"{stats['triangles']:,} tri · {stats['bytes'] / 1024**2:.1f} MB"
        )

    catalog["models"].sort(key=lambda model: str(model.get("name") or model.get("id") or "").lower())
    save_catalog(catalog)
    print(f"GLB DIRETO: {len(added)} arquivo(s) cadastrado(s).")
    if warnings:
        print(f"GLB DIRETO: {len(warnings)} warning(s).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strip", action="store_true", help="remove temporary direct-GLB catalog rows")
    args = parser.parse_args()
    if args.strip:
        strip_direct_entries()
    else:
        sync_direct_entries()


if __name__ == "__main__":
    main()
