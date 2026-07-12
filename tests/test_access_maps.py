import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from app.access_maps import load_access_map_configs, spot_to_access_map
from app.seed_data import SPOTS

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(paths):
    return {path: path.read_bytes() for path in paths if path.exists()}


def _restore(snapshot, paths):
    for path in paths:
        if path in snapshot:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot[path])
        else:
            path.unlink(missing_ok=True)


def test_all_seeded_spot_slugs_resolve_to_access_map():
    mapping = spot_to_access_map()
    slugs = {s['slug'] for s in SPOTS}
    assert slugs <= set(mapping)
    assert mapping['arrifana'].id == mapping['arrifana-reef'].id == 'arrifana'
    assert mapping['monte-clerigo'].id == mapping['monte-clerigo-south'].id == 'monte-clerigo'
    assert mapping['bordeira-north'].id == mapping['bordeira-central'].id == 'bordeira'
    assert mapping['amado'].id == mapping['amado-south'].id == 'amado'


def test_config_schema_contains_required_sections():
    required = ['destination:', 'parking:', 'road_entry:', 'driving_route:', 'walking_route:', 'surf_zones:', 'viewport:', 'verified: false']
    for path in sorted((ROOT / 'data' / 'access-maps').glob('*.yaml')):
        text = path.read_text(encoding='utf-8')
        for needle in required:
            assert needle in text, f'{path} missing {needle}'


def test_generator_records_missing_osm_fixture_without_inventing_svg():
    generated_dir = ROOT / 'data' / 'access-maps-generated'
    static_dir = ROOT / 'app' / 'static' / 'access-maps'
    touched = list(generated_dir.glob('*.source.geojson')) + list(static_dir.glob('*.svg')) + list(generated_dir.glob('*.json'))
    snapshot = _snapshot(touched)
    try:
        for path in generated_dir.glob('*.source.geojson'):
            path.unlink()
        for path in static_dir.glob('*.svg'):
            path.unlink()
        subprocess.run([sys.executable, '-m', 'app.tools.generate_access_maps'], cwd=ROOT, check=True)
        configs = load_access_map_configs()
        for map_id in configs:
            meta_path = generated_dir / f'{map_id}.json'
            assert meta_path.exists()
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            assert meta['requires_manual_review'] is True
            assert meta['verified'] is False
            assert meta['osm_data_timestamp'] is None
            assert any('No local OpenStreetMap raw/vector fixture' in w for w in meta['warnings'])
            assert not (static_dir / f'{map_id}.svg').exists()
    finally:
        _restore(snapshot, touched)


def test_generator_renders_local_osm_geojson_fixture_without_external_images():
    fixture_path = ROOT / 'data' / 'access-maps-generated' / 'odeceixe.source.geojson'
    svg_path = ROOT / 'app' / 'static' / 'access-maps' / 'odeceixe.svg'
    meta_path = ROOT / 'data' / 'access-maps-generated' / 'odeceixe.json'
    touched = [fixture_path, svg_path, meta_path]
    snapshot = _snapshot(touched)
    try:
        fixture_path.write_text(json.dumps({
            'type': 'FeatureCollection',
            'properties': {
                'osm_data_timestamp': '2026-07-12T00:00:00Z',
                'route_provider': 'test local OSM-derived fixture',
                'source_coordinates': {'bbox': [-8.802, 37.438, -8.794, 37.444]},
            },
            'features': [
                {'type': 'Feature', 'properties': {'layer': 'coastline', 'osm_type': 'way', 'osm_id': 1001, 'label': 'OSM coastline fixture'}, 'geometry': {'type': 'LineString', 'coordinates': [[-8.801, 37.438], [-8.800, 37.444]]}},
                {'type': 'Feature', 'properties': {'layer': 'road', 'highway': 'tertiary', 'osm_type': 'way', 'osm_id': 1002, 'label': 'Access road fixture'}, 'geometry': {'type': 'LineString', 'coordinates': [[-8.794, 37.442], [-8.798, 37.441]]}},
                {'type': 'Feature', 'properties': {'layer': 'parking', 'amenity': 'parking', 'osm_type': 'way', 'osm_id': 1003, 'label': 'Parking fixture'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[-8.7984, 37.4410], [-8.7980, 37.4410], [-8.7980, 37.4414], [-8.7984, 37.4414], [-8.7984, 37.4410]]]}},
                {'type': 'Feature', 'properties': {'layer': 'driving_route', 'label': 'Driving route fixture'}, 'geometry': {'type': 'LineString', 'coordinates': [[-8.794, 37.442], [-8.7982, 37.4412]]}},
                {'type': 'Feature', 'properties': {'layer': 'walking_route', 'label': 'Walking route fixture'}, 'geometry': {'type': 'LineString', 'coordinates': [[-8.7982, 37.4412], [-8.8005, 37.4400]]}},
            ],
        }), encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'app.tools.generate_access_maps', '--map-id', 'odeceixe'], cwd=ROOT, check=True)
        assert svg_path.exists()
        text = svg_path.read_text(encoding='utf-8')
        assert '<title' in text
        assert '<desc' in text
        assert '© OpenStreetMap contributors' in text
        assert '<image' not in text
        assert 'href="http' not in text
        assert 'google' not in text.lower()
        assert 'driving-route' in text
        assert 'walking-route' in text
        assert 'scale-bar' in text
        meta = json.loads((ROOT / 'data' / 'access-maps-generated' / 'odeceixe.json').read_text(encoding='utf-8'))
        assert meta['source_feature_count'] == 5
        assert 'way/1001' in meta['source_osm_object_ids']
        assert meta['requires_manual_review'] is True
        assert meta['verified'] is False
    finally:
        _restore(snapshot, touched)


def test_existing_access_map_svgs_if_any_are_safe():
    for path in sorted((ROOT / 'app' / 'static' / 'access-maps').glob('*.svg')):
        root = ET.parse(path).getroot()
        text = path.read_text(encoding='utf-8')
        assert 'viewBox' in root.attrib
        assert '© OpenStreetMap contributors' in text
        assert '<image' not in text
        assert 'href="http' not in text
        assert 'google' not in text.lower()
        assert 'driving-route' in text
        assert 'walking-route' in text
        assert 'scale-bar' in text
