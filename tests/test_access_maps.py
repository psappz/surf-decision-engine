import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from app.access_maps import load_access_map_configs, spot_to_access_map
from app.seed_data import SPOTS

ROOT = Path(__file__).resolve().parents[1]


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
    subprocess.run([sys.executable, '-m', 'app.tools.generate_access_maps'], cwd=ROOT, check=True)
    configs = load_access_map_configs()
    for map_id in configs:
        meta_path = ROOT / 'data' / 'access-maps-generated' / f'{map_id}.json'
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        assert meta['requires_manual_review'] is True
        assert meta['verified'] is False
        assert meta['osm_data_timestamp'] is None
        assert any('No local OpenStreetMap raw/vector fixture' in w for w in meta['warnings'])
        assert not (ROOT / 'app' / 'static' / 'access-maps' / f'{map_id}.svg').exists()


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
