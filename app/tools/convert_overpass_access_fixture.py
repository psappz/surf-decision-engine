from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.access_maps import GENERATED_DIR


def _layer(tags: dict[str, Any]) -> str:
    if tags.get('amenity') == 'parking':
        return 'parking'
    if tags.get('natural') == 'coastline':
        return 'coastline'
    if tags.get('natural') == 'beach':
        return 'beach'
    highway = tags.get('highway')
    if highway in {'footway', 'path', 'steps', 'pedestrian', 'cycleway'}:
        return 'path'
    if highway in {'track', 'service'}:
        return 'track'
    if highway:
        return 'road'
    return 'road'


def _properties(element: dict[str, Any]) -> dict[str, Any]:
    tags = element.get('tags') or {}
    props = dict(tags)
    props['layer'] = _layer(tags)
    props['osm_type'] = element.get('type')
    props['osm_id'] = element.get('id')
    if 'name' not in props:
        props['label'] = props['layer'].replace('_', ' ').title()
    access_values = {k: v for k, v in tags.items() if k in {'access', 'vehicle', 'motor_vehicle', 'foot', 'private'}}
    if any(v in {'no', 'private', 'destination', 'permissive'} for v in access_values.values()):
        props['access_tags'] = access_values
    return props


def convert(overpass_json: Path, output_geojson: Path) -> int:
    source = json.loads(overpass_json.read_text(encoding='utf-8'))
    features: list[dict[str, Any]] = []
    for element in source.get('elements', []):
        etype = element.get('type')
        tags = element.get('tags') or {}
        if etype == 'node' and 'lat' in element and 'lon' in element:
            if tags.get('amenity') != 'parking':
                continue
            geometry = {'type': 'Point', 'coordinates': [element['lon'], element['lat']]}
        elif etype == 'way' and element.get('geometry'):
            coords = [[point['lon'], point['lat']] for point in element['geometry'] if 'lon' in point and 'lat' in point]
            if len(coords) < 2:
                continue
            closed = coords[0] == coords[-1]
            polygon_tags = tags.get('amenity') == 'parking' or tags.get('natural') == 'beach'
            geometry = {'type': 'Polygon', 'coordinates': [coords]} if closed and polygon_tags else {'type': 'LineString', 'coordinates': coords}
        else:
            continue
        features.append({'type': 'Feature', 'properties': _properties(element), 'geometry': geometry})

    fixture = {
        'type': 'FeatureCollection',
        'properties': {
            'retrieved_at': source.get('osm3s', {}).get('timestamp_osm_base') or datetime.now(UTC).isoformat(),
            'osm_data_timestamp': source.get('osm3s', {}).get('timestamp_osm_base'),
            'route_provider': 'manual Overpass export converted locally; routes still require review/curation',
            'source_coordinates': {},
        },
        'features': features,
    }
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(fixture, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Wrote {len(features)} features to {output_geojson}. Add/curate driving_route and walking_route features before relying on route geometry.')
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description='Convert a saved Overpass JSON response into a WaveWatch local access-map GeoJSON fixture.')
    parser.add_argument('overpass_json', type=Path, help='Saved Overpass JSON response with out body geom.')
    parser.add_argument('--map-id', required=True, help='Access map id, e.g. odeceixe')
    parser.add_argument('--output', type=Path, help='Output GeoJSON path. Defaults to data/access-maps-generated/<map-id>.source.geojson')
    args = parser.parse_args()
    output = args.output or (GENERATED_DIR / f'{args.map_id}.source.geojson')
    raise SystemExit(convert(args.overpass_json, output))


if __name__ == '__main__':
    main()
