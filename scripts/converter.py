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
AUTO_MAX_ATTEMPTS = 5


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
    return {
        'mesh_instances': len(instances),
        'triangles': triangles,
        'materials': len(document.get('materials', [])),
        'bytes': len(data),
    }


def _patch_gltf_axis(target):
    """Rotate STEP/OCCT Z-up output to glTF Y-up without rescaling geometry."""
    data = target.read_bytes()
    size, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A:
        raise ValueError('JSON inicial GLB ausente')
    document = json.loads(data[20:20+size])
    nodes = document.setdefault('nodes', [])
    q = 0.7071067811865476
    for scene in document.get('scenes', []):
        root_id = len(nodes)
        nodes.append({
            'name': 'STEP Z-up to glTF Y-up',
            'rotation': [-q, 0.0, 0.0, q],
            'children': scene.get('nodes', []),
        })
        scene['nodes'] = [root_id]
    encoded = json.dumps(document, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    encoded += b' ' * (-len(encoded) % 4)
    tail = data[20+size:]
    target.write_bytes(
        struct.pack('<III', 0x46546C67, 2, 20 + len(encoded) + len(tail))
        + struct.pack('<II', len(encoded), 0x4E4F534A)
        + encoded
        + tail
    )


def convert_one(source, target, tolerance, angular):
    """Read STEP directly into XCAF, mesh it, and export GLB."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Message import Message_ProgressRange
    from OCP.RWGltf import RWGltf_CafWriter
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    try:
        from OCP.TColStd import TColStd_IndexedDataMapOfStringString
    except ImportError:
        from OCP.collections import (
            IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString
            as TColStd_IndexedDataMapOfStringString,
        )

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    app.InitDocument(doc)

    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    reader.SetLayerMode(True)
    status = reader.ReadFile(str(source))
    if status != IFSelect_RetDone:
        raise ValueError(f'OpenCascade não conseguiu ler o STEP ({status})')
    if not reader.Transfer(doc):
        raise ValueError('OpenCascade não conseguiu transferir o STEP para XCAF')

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() < 1:
        raise ValueError('STEP sem formas exportáveis')

    for index in range(1, roots.Length() + 1):
        shape = shape_tool.GetShape_s(roots.Value(index))
        if shape.IsNull():
            continue
        mesher = BRepMesh_IncrementalMesh(shape, tolerance, False, angular, True)
        mesher.Perform()
        if not mesher.IsDone():
            raise ValueError(f'Falha ao triangular a forma raiz {index}')

    writer = RWGltf_CafWriter(TCollection_AsciiString(str(target)), True)
    writer.SetMergeFaces(True)
    if not writer.Perform(doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange()):
        raise ValueError('OCCT não conseguiu exportar a montagem')

    _patch_gltf_axis(target)
    inspect_glb(target)


def _auto_triangle_target(mesh_instances, hard_limit):
    """Choose a game-oriented triangle budget from the number of physical pieces."""
    if mesh_instances <= 100:
        target = 800_000
    elif mesh_instances <= 250:
        target = 650_000
    elif mesh_instances <= 500:
        target = 500_000
    elif mesh_instances <= 800:
        target = 400_000
    elif mesh_instances <= 1200:
        target = 300_000
    else:
        target = 250_000
    return min(target, int(hard_limit))


def _run_worker(source, target, tolerance, angular, timeout):
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        '--worker',
        str(source),
        str(target),
        str(tolerance),
        str(angular),
    ]
    result = subprocess.run(command, timeout=timeout, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Conversor falhou: ' + (result.stderr or result.stdout)[-1400:])
    return inspect_glb(target)


def _warn_complexity(source, stats, config):
    warnings = []
    if stats['mesh_instances'] > config['max_mesh_instances']:
        message = (
            f'{source.name}: {stats["mesh_instances"]} peças excedem o recomendado '
            f'de {config["max_mesh_instances"]}; o modelo será publicado mesmo assim.'
        )
        print(f'::warning title=Modelo com muitas peças::{message}', flush=True)
        warnings.append(message)
    if stats['triangles'] > config['max_triangles']:
        message = (
            f'{source.name}: {stats["triangles"]:,} triângulos excedem o recomendado '
            f'de {int(config["max_triangles"]):,}; o modelo será publicado mesmo assim.'
        )
        print(f'::warning title=Modelo com muitos triângulos::{message}', flush=True)
        warnings.append(message)
    return warnings


def _auto_convert(source, stage, model_id, config):
    """Mesh repeatedly, increasing deflection only as much as the model needs."""
    tolerance = float(config['tolerance_mm'])
    angular = float(config['angular_tolerance_rad'])
    max_bytes = int(config['max_output_mb'] * 1024**2)
    hard_triangles = int(config['max_triangles'])
    attempts = []
    best = None
    target_triangles = None

    for attempt in range(1, AUTO_MAX_ATTEMPTS + 1):
        attempt_file = stage / f'{model_id}.auto{attempt}.glb'
        stats = _run_worker(
            source,
            attempt_file,
            tolerance,
            angular,
            config['timeout_seconds'],
        )
        if target_triangles is None:
            target_triangles = _auto_triangle_target(stats['mesh_instances'], hard_triangles)

        tri_pressure = stats['triangles'] / max(1, target_triangles)
        byte_pressure = stats['bytes'] / max(1, max_bytes)
        pressure = max(tri_pressure, byte_pressure)
        score = (pressure, stats['triangles'], stats['bytes'])
        record = {
            'file': attempt_file,
            'stats': stats,
            'tolerance': tolerance,
            'angular': angular,
            'score': score,
        }
        attempts.append(record)
        if best is None or score < best['score']:
            best = record

        print(
            'AUTO '
            f'{source.name} tentativa {attempt}/{AUTO_MAX_ATTEMPTS}: '
            f'{stats["mesh_instances"]} peças · {stats["triangles"]:,} tri · '
            f'{stats["bytes"] / 1024**2:.1f} MB · '
            f'tol={tolerance:.4g} · ang={angular:.3g} · meta={target_triangles:,}',
            flush=True,
        )

        if stats['triangles'] <= target_triangles and stats['bytes'] <= max_bytes:
            best = record
            break

        if attempt >= 2:
            previous = attempts[-2]['stats']
            tri_gain = 1.0 - stats['triangles'] / max(1, previous['triangles'])
            byte_gain = 1.0 - stats['bytes'] / max(1, previous['bytes'])
            if max(tri_gain, byte_gain) < 0.015:
                print('AUTO: ganho abaixo de 1.5%; mantendo a melhor malha obtida.', flush=True)
                break

        linear_factor = min(2.5, max(1.25, math.sqrt(max(1.0, pressure))))
        angular_factor = min(1.65, max(1.12, max(1.0, pressure) ** 0.25))
        new_tolerance = min(10.0, tolerance * linear_factor)
        new_angular = min(1.0, angular * angular_factor)
        if math.isclose(new_tolerance, tolerance) and math.isclose(new_angular, angular):
            break
        tolerance, angular = new_tolerance, new_angular

    if best is None:
        raise ValueError('AUTO não produziu nenhuma malha válida')

    stats = best['stats']
    if stats['bytes'] > max_bytes:
        raise ValueError(f'AUTO não conseguiu reduzir o GLB abaixo de {config["max_output_mb"]} MB')

    complexity_warnings = _warn_complexity(source, stats, config)
    first_triangles = attempts[0]['stats']['triangles']
    reduction = 100.0 * (1.0 - stats['triangles'] / max(1, first_triangles))
    quality = {
        'optimization': 'auto',
        'original_triangles': first_triangles,
        'auto_target_triangles': target_triangles,
        'auto_target_met': stats['triangles'] <= target_triangles and stats['bytes'] <= max_bytes,
        'reduction_percent': round(max(0.0, reduction), 1),
        'mesh_tolerance_mm': round(best['tolerance'], 6),
        'angular_tolerance_rad': round(best['angular'], 6),
        'auto_attempts': len(attempts),
    }
    if complexity_warnings:
        quality['complexity_warnings'] = complexity_warnings

    print(
        f'AUTO ESCOLHIDO {source.name}: {stats["triangles"]:,} tri · '
        f'{quality["reduction_percent"]:.1f}% redução · '
        f'tol={quality["mesh_tolerance_mm"]} · ang={quality["angular_tolerance_rad"]}',
        flush=True,
    )
    return best['file'], stats, quality


def load_config():
    config = json.loads((ROOT / 'config.json').read_text())
    bounds = {
        'tolerance_mm': (.001, 10),
        'angular_tolerance_rad': (.01, 1),
        'max_input_mb': (1, 25),
        'max_output_mb': (1, 25),
        'max_mesh_instances': (1, 2000),
        'max_triangles': (1, 2000000),
        'timeout_seconds': (10, 600),
    }
    for key, (low, high) in bounds.items():
        value = config[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f'Configuração inválida: {key}')
    return config


def build():
    source_dir, output_dir = ROOT / 'originais', ROOT / 'modelos'
    inside(source_dir, ROOT)
    inside(output_dir, ROOT)
    output_dir.mkdir(exist_ok=True)
    config = load_config()
    fingerprint = hashlib.sha256(
        (
            json.dumps(config, sort_keys=True)
            + digest(Path(__file__))
            + digest(ROOT / 'requirements.txt')
        ).encode()
    ).hexdigest()
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
                cached = (
                    entry.get('source_sha256') == source_hash
                    and entry.get('converter') == fingerprint
                    and target.is_file()
                    and entry.get('sha256') == digest(target)
                )

                if cached:
                    stats = inspect_glb(target)
                    output_hash = digest(target)
                    quality = {
                        key: entry[key]
                        for key in (
                            'optimization', 'original_triangles', 'auto_target_triangles',
                            'auto_target_met', 'reduction_percent', 'mesh_tolerance_mm',
                            'angular_tolerance_rad', 'auto_attempts', 'complexity_warnings',
                        )
                        if key in entry
                    }
                    print(f'CACHE {relative}', flush=True)
                else:
                    print(f'CONVERTENDO {relative} · AUTO', flush=True)
                    staged, stats, quality = _auto_convert(source, stage, model_id, config)
                    output_hash = digest(staged)
                    changed.append((staged, target))

                if stats['bytes'] > config['max_output_mb'] * 1024**2:
                    raise ValueError('GLB excede o limite de saída; simplifique o STEP')

                # Complexity thresholds are recommendations, not publication blockers.
                final_warnings = _warn_complexity(source, stats, config)
                if final_warnings:
                    quality['complexity_warnings'] = final_warnings

                def label(key, default, limit):
                    value = metadata.get(key, default)
                    if not isinstance(value, str):
                        raise ValueError(f'Metadado {key} precisa ser texto')
                    return value[:limit]

                entries.append({
                    'id': model_id,
                    'name': label('name', source.stem, 100),
                    'author': label('author', '', 100),
                    'description': label('description', '', 500),
                    'source': relative,
                    'file': file,
                    **stats,
                    **quality,
                    'sha256': output_hash,
                    'source_sha256': source_hash,
                    'converter': fingerprint,
                })
            except Exception as error:
                failures.append(f'{source.name}: {error}')

        if failures:
            raise RuntimeError('\n'.join(failures) + '\nCatálogo anterior preservado; nenhuma saída publicada.')

        for staged, target in changed:
            shutil.copyfile(staged, target)

        active = {entry['file'] for entry in entries}
        for entry in old.values():
            file = entry.get('file', '')
            if file not in active and re.fullmatch(r'modelos/[a-z0-9-]+\.glb', file):
                inside(ROOT / file, output_dir).unlink(missing_ok=True)

        catalog = {'schema_version': VERSION, 'models': entries}
        with tempfile.NamedTemporaryFile('w', dir=ROOT, delete=False, encoding='utf-8') as out:
            json.dump(catalog, out, ensure_ascii=False, indent=2)
            out.write('\n')
            temporary_catalog = out.name
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
