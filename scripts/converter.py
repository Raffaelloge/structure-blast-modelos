#!/usr/bin/env python3
"""Incremental STEP assembly -> self-contained GLB catalog. Run from any cwd."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = 1

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inside(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Caminho não permitido: {path.name}")
    return path

def inspect_glb(path):
    """Validate GLB container, embedded resources and approximate scene complexity."""
    data = path.read_bytes()
    if len(data) < 20 or struct.unpack_from('<III', data) != (0x46546C67, 2, len(data)):
        raise ValueError('GLB inválido ou incompleto')
    offset, document = 12, None
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError('Cabeçalho GLB truncado')
        size, kind = struct.unpack_from('<II', data, offset)
        offset += 8
        if size % 4 or offset + size > len(data):
            raise ValueError('Chunk GLB inválido')
        if kind == 0x4E4F534A:
            document = json.loads(data[offset:offset+size])
        offset += size
    if document is None:
        raise ValueError('GLB sem JSON')
    for obj in document.get('buffers', []) + document.get('images', []):
        if obj.get('uri') and not obj['uri'].startswith('data:'):
            raise ValueError('GLB depende de arquivo externo')
    meshes = document.get('meshes', [])
    instances = [n['mesh'] for n in document.get('nodes', []) if 'mesh' in n]
    triangles = 0
    for mesh_id in instances:
        for primitive in meshes[mesh_id].get('primitives', []):
            mode = primitive.get('mode', 4)
            index = primitive.get('indices', primitive.get('attributes', {}).get('POSITION'))
            if index is None:
                continue
            count = document['accessors'][index]['count']
            if mode == 4:
                triangles += count // 3
            elif mode in (5, 6):
                triangles += max(0, count - 2)
    if not instances or not triangles:
        raise ValueError('Nenhuma malha triangular exportada')
    return {'mesh_instances': len(instances), 'triangles': triangles,
            'materials': len(document.get('materials', [])), 'bytes': len(data)}

def convert_one(source, target, tolerance, angular):
    import cadquery as cq
    assembly = cq.Assembly.load(str(source), importType='STEP')
    # Export the assembly, not a fused solid: keep components and available colors.
    from cadquery.occ_impl.exporters.assembly import toCAF
    from OCP.RWGltf import RWGltf_CafWriter
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TColStd import TColStd_IndexedDataMapOfStringString
    from OCP.Message import Message_ProgressRange
    # Same OCCT assembly route used by CadQuery; merge faces within each part
    # to avoid importing a separate game mesh for every individual CAD face.
    assembly.loc *= cq.Location((0, 0, 0), (1, 0, 0), -90)
    _, doc = toCAF(assembly, True, True, tolerance, angular)
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(target)), True)
    writer.SetMergeFaces(True)
    if not writer.Perform(doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange()):
        raise ValueError('OCCT não conseguiu exportar a montagem')
    # CadQuery imports STEP in mm. glTF uses meters; keep geometry untouched and
    # add one explicit scale node per scene. Binary accessor offsets stay valid.
    data = target.read_bytes()
    size, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A:
        raise ValueError('JSON inicial GLB ausente')
    document = json.loads(data[20:20+size])
    nodes = document.setdefault('nodes', [])
    for scene in document.get('scenes', []):
        root_id = len(nodes)
        nodes.append({'name': 'STEP millimeters to meters', 'scale': [.001, .001, .001],
                      'children': scene.get('nodes', [])})
        scene['nodes'] = [root_id]
    encoded = json.dumps(document, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    encoded += b' ' * (-len(encoded) % 4)
    tail = data[20+size:]
    target.write_bytes(struct.pack('<III', 0x46546C67, 2, 20+len(encoded)+len(tail))
                       + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded + tail)
    inspect_glb(target)

def load_config():
    config = json.loads((ROOT / 'config.json').read_text())
    bounds = {'tolerance_mm': (.001, 10), 'angular_tolerance_rad': (.01, 1),
              'max_input_mb': (1, 25), 'max_output_mb': (1, 25),
              'max_mesh_instances': (1, 2000), 'max_triangles': (1, 2000000),
              'timeout_seconds': (10, 600)}
    for key, (low, high) in bounds.items():
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Configuração inválida: {key}')
    return config

def build():
    source_dir, output_dir = ROOT / 'originais', ROOT / 'modelos'
    inside(source_dir, ROOT); inside(output_dir, ROOT)
    output_dir.mkdir(exist_ok=True)
    config = load_config()
    fingerprint = hashlib.sha256((json.dumps(config, sort_keys=True) + digest(Path(__file__))
                                  + digest(ROOT / 'requirements.txt')).encode()).hexdigest()
    catalog_path = ROOT / 'catalogo.json'
    previous = json.loads(catalog_path.read_text()) if catalog_path.exists() else {'models': []}
    old = {m['id']: m for m in previous['models']}
    sources = sorted(p for p in source_dir.rglob('*') if p.suffix.lower() in ('.step', '.stp'))
    entries, failures = [], []
    with tempfile.TemporaryDirectory(prefix='step-library-') as temporary:
        stage = Path(temporary)
        changed = []
        for source in sources:
            try:
                inside(source, source_dir)
                if not source.is_file() or source.stat().st_size > config['max_input_mb'] * 1024**2:
                    raise ValueError('STEP excede o limite de entrada ou não é arquivo')
                relative = source.relative_to(ROOT).as_posix()
                slug = re.sub(r'[^a-z0-9]+', '-', source.stem.lower()).strip('-')[:60] or 'modelo'
                model_id = slug + '-' + hashlib.sha256(relative.encode()).hexdigest()[:10]
                file = f'modelos/{model_id}.glb'
                source_hash = digest(source)
                metadata_path = source.with_suffix('.json')
                metadata = {}
                if metadata_path.exists():
                    inside(metadata_path, source_dir)
                    if metadata_path.stat().st_size > 16384:
                        raise ValueError('Metadados excedem 16 KB')
                    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
                    if not isinstance(metadata, dict):
                        raise ValueError('Metadados precisam ser um objeto JSON')
                entry = old.get(model_id, {})
                target = inside(ROOT / file, output_dir)
                cached = (entry.get('source_sha256') == source_hash and entry.get('converter') == fingerprint
                          and target.is_file() and entry.get('sha256') == digest(target))
                if cached:
                    stats = inspect_glb(target)
                    output_hash = digest(target)
                    print(f'CACHE {relative}', flush=True)
                else:
                    staged = stage / (model_id + '.glb')
                    print(f'CONVERTENDO {relative}', flush=True)
                    command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(source), str(staged),
                               str(config['tolerance_mm']), str(config['angular_tolerance_rad'])]
                    result = subprocess.run(command, timeout=config['timeout_seconds'], capture_output=True, text=True)
                    if result.returncode:
                        raise ValueError('Conversor falhou: ' + (result.stderr or result.stdout)[-1400:])
                    stats = inspect_glb(staged)
                    output_hash = digest(staged)
                    changed.append((staged, target))
                if stats['bytes'] > config['max_output_mb'] * 1024**2:
                    raise ValueError('GLB excede o limite de saída; simplifique o STEP')
                if stats['mesh_instances'] > config['max_mesh_instances'] or stats['triangles'] > config['max_triangles']:
                    raise ValueError(f'Modelo complexo demais: {stats}; simplifique ou ajuste config.json')
                def label(key, default, limit):
                    value = metadata.get(key, default)
                    if not isinstance(value, str):
                        raise ValueError(f'Metadado {key} precisa ser texto')
                    return value[:limit]
                entries.append({'id': model_id, 'name': label('name', source.stem, 100),
                                'author': label('author', '', 100), 'description': label('description', '', 500),
                                'source': relative, 'file': file, **stats, 'sha256': output_hash,
                                'source_sha256': source_hash, 'converter': fingerprint})
            except Exception as error:
                failures.append(f'{source.name}: {error}')
        if failures:
            raise RuntimeError('\n'.join(failures) + '\nCatálogo anterior preservado; nenhuma saída publicada.')
        # Publish only if every input succeeded; source deletions remove known generated outputs.
        for staged, target in changed:
            shutil.copyfile(staged, target)
        active = {entry['file'] for entry in entries}
        for entry in old.values():
            file = entry.get('file', '')
            if file not in active and re.fullmatch(r'modelos/[a-z0-9-]+\.glb', file):
                inside(ROOT / file, output_dir).unlink(missing_ok=True)
        catalog = {'schema_version': VERSION, 'models': entries}
        with tempfile.NamedTemporaryFile('w', dir=ROOT, delete=False, encoding='utf-8') as out:
            json.dump(catalog, out, ensure_ascii=False, indent=2); out.write('\n'); temporary_catalog = out.name
        os.replace(temporary_catalog, catalog_path)
        print(f'OK: {len(entries)} modelos; {len(changed)} convertidos; catálogo atualizado.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', nargs=4, metavar=('STEP', 'GLB', 'TOLERANCE', 'ANGLE'))
    args = parser.parse_args()
    try:
        if args.worker:
            source, target, tolerance, angular = args.worker
            convert_one(Path(source), Path(target), float(tolerance), float(angular))
        else:
            build()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
