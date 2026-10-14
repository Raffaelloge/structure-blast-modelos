#!/usr/bin/env python3
"""Normalize converted STEP GLBs to the orientation expected by Structure Blast.

The STEP/XCAF export used by this library needs a root X rotation before it is
shown in a Y-up renderer. The previous pipeline used -90 degrees; the models in
this library use the opposite vertical sense, so the correct root correction is
+90 degrees. This pass is idempotent: it sets the quaternion absolutely instead
of multiplying rotations, then refreshes the catalog SHA-256.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'catalogo.json'
ROOT_NAMES = {'STEP Z-up to glTF Y-up', 'STEP axis correction (+90 X)'}
Q = 0.7071067811865476


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_glb(path: Path) -> bool:
    data = path.read_bytes()
    if len(data) < 20 or struct.unpack_from('<III', data) != (0x46546C67, 2, len(data)):
        raise ValueError(f'GLB inválido: {path}')

    json_size, json_kind = struct.unpack_from('<II', data, 12)
    if json_kind != 0x4E4F534A:
        raise ValueError(f'GLB sem JSON inicial: {path}')

    document = json.loads(data[20:20 + json_size])
    changed = False
    for node in document.get('nodes', []):
        if node.get('name') in ROOT_NAMES:
            wanted = [Q, 0.0, 0.0, Q]
            if node.get('rotation') != wanted or node.get('name') != 'STEP axis correction (+90 X)':
                node['rotation'] = wanted
                node['name'] = 'STEP axis correction (+90 X)'
                changed = True

    if not changed:
        return False

    encoded = json.dumps(document, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    encoded += b' ' * (-len(encoded) % 4)
    tail = data[20 + json_size:]
    path.write_bytes(
        struct.pack('<III', 0x46546C67, 2, 20 + len(encoded) + len(tail))
        + struct.pack('<II', len(encoded), 0x4E4F534A)
        + encoded
        + tail
    )
    return True


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    changed_count = 0
    for model in catalog.get('models', []):
        file = model.get('file')
        source = str(model.get('source', '')).lower()
        if not file or not source.endswith(('.step', '.stp')):
            continue
        path = (ROOT / file).resolve()
        if not path.is_relative_to((ROOT / 'modelos').resolve()) or not path.is_file():
            raise ValueError(f'Arquivo de catálogo inválido: {file}')
        changed = patch_glb(path)
        model['sha256'] = sha256(path)
        model['bytes'] = path.stat().st_size
        model['axis_correction'] = '+90deg_x_to_y_up'
        if changed:
            changed_count += 1
            print(f'ORIENTAÇÃO corrigida: {file}', flush=True)

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Orientação: {changed_count} GLB(s) alterado(s).', flush=True)


if __name__ == '__main__':
    main()
