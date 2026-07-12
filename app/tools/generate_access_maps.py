from __future__ import annotations

import argparse
import json
from datetime import datetime, UTC
from pathlib import Path
from xml.etree import ElementTree as ET

from app.access_maps import CONFIG_DIR, GENERATED_DIR, STATIC_DIR, load_access_map_configs

GENERATOR_VERSION = 'access-map-generator-v1-offline-fixture-required'


def validate_svg(path: Path) -> list[str]:
    warnings: list[str] = []
    root = ET.parse(path).getroot()
    text = path.read_text(encoding='utf-8')
    if 'viewBox' not in root.attrib:
        warnings.append('SVG is missing viewBox.')
    if '© OpenStreetMap contributors' not in text:
        warnings.append('SVG is missing visible OpenStreetMap attribution.')
    forbidden = ['<image', 'href="http', 'google', 'Google', 'maps.googleapis', 'khms']
    for needle in forbidden:
        if needle in text:
            warnings.append(f'SVG contains forbidden external/proprietary reference: {needle}')
    return warnings


def generate() -> int:
    configs = load_access_map_configs(CONFIG_DIR)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    wrote = 0
    for map_id, cfg in configs.items():
        fixture = GENERATED_DIR / f'{map_id}.source.geojson'
        warnings = []
        if not fixture.exists():
            warnings.append('No local OpenStreetMap raw/vector fixture found; SVG was not generated to avoid inventing roads, routes, parking, or access restrictions.')
            meta_path = GENERATED_DIR / f'{map_id}.json'
            generated_at = now
            if meta_path.exists():
                try:
                    generated_at = json.loads(meta_path.read_text(encoding='utf-8')).get('generated_at') or now
                except json.JSONDecodeError:
                    generated_at = now
            meta = {
                'map_id': map_id,
                'generated_at': generated_at,
                'osm_data_timestamp': None,
                'route_provider': None,
                'source_coordinates': {},
                'warnings': warnings,
                'requires_manual_review': True,
                'verified': False,
                'generator_version': GENERATOR_VERSION,
                'config': str(CONFIG_DIR / f'{map_id}.yaml'),
            }
            (GENERATED_DIR / f'{map_id}.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n', encoding='utf-8')
            continue
        raise NotImplementedError('OSM fixture rendering is intentionally blocked until a real local fixture schema is provided and reviewed.')
    print(f'Processed {len(configs)} access-map configs; wrote {wrote} SVG files. Missing local OSM fixtures are recorded as review metadata.')
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate static WaveWatch SVG access maps from local OpenStreetMap vector fixtures.')
    parser.add_argument('--validate-only', action='store_true', help='Validate existing SVG files instead of generating metadata.')
    args = parser.parse_args()
    if args.validate_only:
        errors=[]
        for path in sorted(STATIC_DIR.glob('*.svg')):
            errors.extend(f'{path}: {w}' for w in validate_svg(path))
        if errors:
            raise SystemExit('\n'.join(errors))
        print('Existing access-map SVG validation passed.')
    else:
        raise SystemExit(generate())

if __name__ == '__main__':
    main()
