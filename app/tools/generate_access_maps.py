from __future__ import annotations

import argparse
import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from app.access_maps import CONFIG_DIR, GENERATED_DIR, STATIC_DIR, AccessMapConfig, load_access_map_configs
from app.seed_data import SPOTS

GENERATOR_VERSION = 'access-map-generator-v2-local-osm-geojson'
SVG_WIDTH = 960
SVG_HEIGHT = 620

LAYER_STYLES = {
    'coastline': {'stroke': '#3b82f6', 'stroke_width': 4, 'fill': 'none', 'dash': ''},
    'beach': {'stroke': '#d6a84f', 'stroke_width': 2, 'fill': '#f6e3b4', 'dash': ''},
    'road': {'stroke': '#374151', 'stroke_width': 4, 'fill': 'none', 'dash': ''},
    'track': {'stroke': '#8b5e34', 'stroke_width': 3, 'fill': 'none', 'dash': '8 7'},
    'path': {'stroke': '#16a34a', 'stroke_width': 3, 'fill': 'none', 'dash': '5 6'},
    'parking': {'stroke': '#1d4ed8', 'stroke_width': 2, 'fill': '#dbeafe', 'dash': ''},
    'driving_route': {'stroke': '#111827', 'stroke_width': 6, 'fill': 'none', 'dash': ''},
    'walking_route': {'stroke': '#f97316', 'stroke_width': 5, 'fill': 'none', 'dash': '10 8'},
    'destination': {'stroke': '#be123c', 'stroke_width': 3, 'fill': '#fb7185', 'dash': ''},
    'access_restriction': {'stroke': '#dc2626', 'stroke_width': 3, 'fill': 'none', 'dash': '4 5'},
}


def validate_svg(path: Path) -> list[str]:
    warnings: list[str] = []
    root = ET.parse(path).getroot()
    text = path.read_text(encoding='utf-8')
    if 'viewBox' not in root.attrib:
        warnings.append('SVG is missing viewBox.')
    nsless_tags = {element.tag.rsplit('}', 1)[-1] for element in root.iter()}
    if 'title' not in nsless_tags or 'desc' not in nsless_tags:
        warnings.append('SVG is missing title or desc metadata.')
    if '© OpenStreetMap contributors' not in text:
        warnings.append('SVG is missing visible OpenStreetMap attribution.')
    forbidden = ['<image', 'href="http', 'google', 'Google', 'maps.googleapis', 'khms']
    for needle in forbidden:
        if needle in text:
            warnings.append(f'SVG contains forbidden external/proprietary reference: {needle}')
    return warnings


def _load_geojson(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('type') != 'FeatureCollection':
        raise ValueError(f'{path} must be a GeoJSON FeatureCollection')
    if not isinstance(data.get('features'), list):
        raise ValueError(f'{path} must contain a features list')
    return data


def _coords_from_geometry(geometry: dict) -> list[tuple[float, float]]:
    coords = geometry.get('coordinates')
    gtype = geometry.get('type')
    out: list[tuple[float, float]] = []

    def add_pair(pair):
        if isinstance(pair, list) and len(pair) >= 2:
            lon, lat = pair[0], pair[1]
            if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
                out.append((float(lon), float(lat)))

    if gtype == 'Point':
        add_pair(coords)
    elif gtype == 'LineString':
        for pair in coords or []:
            add_pair(pair)
    elif gtype == 'Polygon':
        for ring in coords or []:
            for pair in ring:
                add_pair(pair)
    elif gtype == 'MultiLineString':
        for line in coords or []:
            for pair in line:
                add_pair(pair)
    elif gtype == 'MultiPolygon':
        for polygon in coords or []:
            for ring in polygon:
                for pair in ring:
                    add_pair(pair)
    return out


def _all_lonlat(features: list[dict]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for feature in features:
        geometry = feature.get('geometry') or {}
        points.extend(_coords_from_geometry(geometry))
    return points


def _projector(points: list[tuple[float, float]]):
    if not points:
        raise ValueError('Cannot render SVG: fixture contains no coordinates')
    min_lon = min(p[0] for p in points)
    max_lon = max(p[0] for p in points)
    min_lat = min(p[1] for p in points)
    max_lat = max(p[1] for p in points)
    if math.isclose(min_lon, max_lon):
        min_lon -= 0.001
        max_lon += 0.001
    if math.isclose(min_lat, max_lat):
        min_lat -= 0.001
        max_lat += 0.001
    pad = 48
    mid_lat = (min_lat + max_lat) / 2
    lon_scale = math.cos(math.radians(mid_lat)) or 1.0
    width_units = (max_lon - min_lon) * lon_scale
    height_units = max_lat - min_lat
    scale = min((SVG_WIDTH - pad * 2) / width_units, (SVG_HEIGHT - pad * 2) / height_units)

    def xy(lon: float, lat: float) -> tuple[float, float]:
        x = pad + ((lon - min_lon) * lon_scale) * scale
        y = SVG_HEIGHT - pad - ((lat - min_lat) * scale)
        return (round(x, 2), round(y, 2))

    meters_per_degree_lon = 111_320 * lon_scale
    meters_per_px = 1 / (scale / meters_per_degree_lon)
    return xy, meters_per_px


def _path_d(geometry: dict, xy) -> str:
    gtype = geometry.get('type')
    coords = geometry.get('coordinates') or []

    def line_to_d(line, close: bool = False) -> str:
        parts = []
        for index, pair in enumerate(line):
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            x, y = xy(float(pair[0]), float(pair[1]))
            parts.append(('M' if index == 0 else 'L') + f' {x} {y}')
        if close and parts:
            parts.append('Z')
        return ' '.join(parts)

    if gtype == 'LineString':
        return line_to_d(coords)
    if gtype == 'Polygon':
        return ' '.join(line_to_d(ring, close=True) for ring in coords)
    if gtype == 'MultiLineString':
        return ' '.join(line_to_d(line) for line in coords)
    if gtype == 'MultiPolygon':
        return ' '.join(line_to_d(ring, close=True) for polygon in coords for ring in polygon)
    return ''


def _feature_layer(feature: dict) -> str:
    props = feature.get('properties') or {}
    layer = str(props.get('layer') or props.get('kind') or '').strip()
    if layer:
        return layer
    highway = props.get('highway')
    amenity = props.get('amenity')
    natural = props.get('natural')
    if amenity == 'parking':
        return 'parking'
    if natural == 'coastline':
        return 'coastline'
    if natural == 'beach':
        return 'beach'
    if highway in {'footway', 'path', 'steps', 'pedestrian'}:
        return 'path'
    if highway in {'track', 'service'}:
        return 'track'
    if highway:
        return 'road'
    return 'road'


def _css_class(layer: str) -> str:
    return layer.replace('_', '-').replace(' ', '-').lower()


def _label(feature: dict, fallback: str) -> str:
    props = feature.get('properties') or {}
    return str(props.get('label') or props.get('name') or fallback)


def _feature_osm_id(feature: dict) -> str | None:
    props = feature.get('properties') or {}
    osm_type = props.get('osm_type') or props.get('@type')
    osm_id = props.get('osm_id') or props.get('@id')
    if osm_type and osm_id:
        return f'{osm_type}/{osm_id}'
    if osm_id:
        return str(osm_id)
    return None


def _seed_center(cfg: AccessMapConfig) -> tuple[float, float] | None:
    by_slug = {str(spot['slug']): spot for spot in SPOTS}
    points = []
    for slug in cfg.spot_slugs:
        spot = by_slug.get(slug)
        if spot and spot.get('longitude') is not None and spot.get('latitude') is not None:
            points.append((float(spot['longitude']), float(spot['latitude'])))
    if not points:
        return None
    return (sum(lon for lon, _ in points) / len(points), sum(lat for _, lat in points) / len(points))


def _meters_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    mid_lat = math.radians((a[1] + b[1]) / 2)
    dx = (a[0] - b[0]) * 111_320 * math.cos(mid_lat)
    dy = (a[1] - b[1]) * 110_574
    return math.hypot(dx, dy)


def _centroid(feature: dict) -> tuple[float, float] | None:
    pts = _coords_from_geometry(feature.get('geometry') or {})
    if not pts:
        return None
    return (sum(lon for lon, _ in pts) / len(pts), sum(lat for _, lat in pts) / len(pts))


def _feature_near_center(feature: dict, center: tuple[float, float], radius_m: float) -> bool:
    return any(_meters_between(point, center) <= radius_m for point in _coords_from_geometry(feature.get('geometry') or {}))


def _clip_line_points(points: list[list[float]], center: tuple[float, float], radius_m: float) -> list[list[float]]:
    return [point for point in points if len(point) >= 2 and _meters_between((float(point[0]), float(point[1])), center) <= radius_m]


def _clip_feature_to_focus(feature: dict, center: tuple[float, float], radius_m: float) -> dict | None:
    geometry = feature.get('geometry') or {}
    gtype = geometry.get('type')
    clipped = dict(feature)
    if gtype == 'LineString':
        line = _clip_line_points(geometry.get('coordinates') or [], center, radius_m)
        if len(line) < 2:
            return None
        clipped['geometry'] = {'type': 'LineString', 'coordinates': line}
        return clipped
    if gtype == 'MultiLineString':
        lines = [line for raw in geometry.get('coordinates') or [] if len(line := _clip_line_points(raw, center, radius_m)) >= 2]
        if not lines:
            return None
        clipped['geometry'] = {'type': 'MultiLineString', 'coordinates': lines}
        return clipped
    return clipped if _feature_near_center(feature, center, radius_m) else None


def _focused_features(features: list[dict], cfg: AccessMapConfig) -> tuple[list[dict], tuple[float, float] | None]:
    center = _seed_center(cfg)
    if center is None:
        return features, None
    focused = [clipped for feature in features if (clipped := _clip_feature_to_focus(feature, center, 620)) is not None]
    required_layers = {'parking', 'beach', 'coastline', 'road', 'path'}
    if not required_layers <= {_feature_layer(feature) for feature in focused}:
        return features, center
    destination = {
        'type': 'Feature',
        'properties': {'layer': 'destination', 'label': 'Surf spot seed coordinate'},
        'geometry': {'type': 'Point', 'coordinates': [center[0], center[1]]},
    }
    return focused + [destination], center


def _metadata_from_fixture(map_id: str, cfg: AccessMapConfig, fixture_path: Path, fixture: dict, warnings: list[str]) -> dict:
    props = fixture.get('properties') or {}
    source_ids = sorted({sid for feature in fixture.get('features', []) if (sid := _feature_osm_id(feature))})
    return {
        'map_id': map_id,
        'generated_at': datetime.now(UTC).isoformat(),
        'osm_data_timestamp': props.get('osm_data_timestamp') or props.get('retrieved_at'),
        'route_provider': props.get('route_provider') or 'local OSM-derived GeoJSON fixture',
        'source_coordinates': props.get('source_coordinates') or {},
        'source_fixture': str(fixture_path),
        'source_feature_count': len(fixture.get('features', [])),
        'source_osm_object_ids': source_ids,
        'warnings': warnings,
        'requires_manual_review': True,
        'verified': bool(cfg.verified and props.get('reviewed') is True),
        'generator_version': GENERATOR_VERSION,
        'config': str(CONFIG_DIR / f'{map_id}.yaml'),
    }


def _scale_bar(meters_per_px: float) -> tuple[int, float]:
    candidates = [25, 50, 100, 200, 500, 1000, 2000]
    for meters in candidates:
        px = meters / meters_per_px
        if 70 <= px <= 180:
            return meters, round(px, 2)
    meters = 100
    return meters, round(meters / meters_per_px, 2)


def render_svg(map_id: str, cfg: AccessMapConfig, fixture_path: Path) -> tuple[str, dict]:
    fixture = _load_geojson(fixture_path)
    original_features = fixture['features']
    features, seed_center = _focused_features(original_features, cfg)
    points = _all_lonlat(features)
    xy, meters_per_px = _projector(points)
    warnings: list[str] = []
    layers = {_feature_layer(feature) for feature in features}
    parking_count = sum(1 for feature in features if _feature_layer(feature) == 'parking')
    mapped_step_counts = sorted({str((feature.get('properties') or {}).get('step_count')) for feature in features if (feature.get('properties') or {}).get('step_count')})
    for required_layer in ['driving_route', 'walking_route', 'parking']:
        if required_layer not in layers:
            warnings.append(f'Fixture has no {required_layer.replace("_", " ")} feature; access sketch requires manual review.')
    if 'coastline' not in layers and 'beach' not in layers:
        warnings.append('Fixture has no coastline or beach feature; shoreline context requires manual review.')
    if seed_center and len(features) < len(original_features):
        warnings.append(f'SVG is focused on OSM objects within roughly 620 m of the stored surf spot coordinate; {len(original_features) - len(features) + 1} outlying OSM features are hidden to keep the access sketch readable.')

    title = html.escape(cfg.title)
    desc = html.escape('OSM-derived access sketch requiring manual review; roads, routes, parking and walking access are rendered only from the local source fixture.')
    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{title}</title>',
        f'<desc id="desc">{desc}</desc>',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<g class="map-frame">',
    ]

    draw_order = ['beach', 'coastline', 'road', 'track', 'path', 'parking', 'access_restriction', 'driving_route', 'walking_route', 'destination']
    ordered = sorted(features, key=lambda feature: draw_order.index(_feature_layer(feature)) if _feature_layer(feature) in draw_order else 99)
    parking_index = 0
    labelled_road_names: set[str] = set()
    labelled_beach_names: set[str] = set()
    for feature in ordered:
        geometry = feature.get('geometry') or {}
        layer = _feature_layer(feature)
        style = LAYER_STYLES.get(layer, LAYER_STYLES['road'])
        klass = _css_class(layer)
        label = html.escape(_label(feature, layer))
        if geometry.get('type') == 'Point':
            coords = _coords_from_geometry(geometry)
            if not coords:
                continue
            x, y = xy(coords[0][0], coords[0][1])
            radius = 12 if layer in {'parking', 'destination'} else 7
            fill = style.get('fill') if style.get('fill') != 'none' else style['stroke']
            text = label
            if layer == 'parking':
                parking_index += 1
                text = f'P{parking_index} OSM parking'
            elif layer == 'destination':
                text = 'Surf spot approx.'
            svg.append(f'<g class="{klass}" aria-label="{html.escape(text)}"><circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}" stroke="{style["stroke"]}" stroke-width="3"/><text x="{x + 16}" y="{y - 10}" font-size="17" font-weight="700" fill="#111827">{html.escape(text)}</text></g>')
            continue
        path_d = _path_d(geometry, xy)
        if not path_d:
            continue
        dash = f' stroke-dasharray="{style["dash"]}"' if style['dash'] else ''
        fill = style['fill'] if geometry.get('type') in {'Polygon', 'MultiPolygon'} else 'none'
        svg.append(f'<path class="{klass}" d="{path_d}" fill="{fill}" stroke="{style["stroke"]}" stroke-width="{style["stroke_width"]}" stroke-linecap="round" stroke-linejoin="round" opacity="0.92"{dash}><title>{label}</title></path>')
        center = _centroid(feature)
        props = feature.get('properties') or {}
        if center:
            cx, cy = xy(center[0], center[1])
            if layer == 'parking':
                parking_index += 1
                p_label = f'P{parking_index}'
                svg.append(f'<g class="parking-label" aria-label="{p_label} OSM parking"><circle cx="{cx}" cy="{cy}" r="13" fill="#1d4ed8"/><text x="{cx - 7}" y="{cy + 5}" font-size="15" font-weight="800" fill="white">{p_label}</text></g>')
            elif layer == 'path' and props.get('highway') == 'steps' and props.get('step_count'):
                step_text = f'steps {html.escape(str(props["step_count"]))}'
                svg.append(f'<text class="steps-label" x="{cx + 8}" y="{cy - 8}" font-size="14" font-weight="700" fill="#b45309">{step_text}</text>')
            elif layer == 'road' and props.get('name') and props.get('name') not in labelled_road_names and str(props['name']).startswith('Estrada da Praia'):
                road_name = html.escape(str(props['name']))
                labelled_road_names.add(str(props['name']))
                svg.append(f'<text class="road-label" x="{cx + 10}" y="{cy + 18}" font-size="12" fill="#111827">{road_name}</text>')
            elif layer == 'beach' and props.get('name') and props.get('name') not in labelled_beach_names:
                beach_name = html.escape(str(props['name']))
                labelled_beach_names.add(str(props['name']))
                svg.append(f'<text class="beach-label" x="{cx + 14}" y="{cy + 16}" font-size="16" font-weight="700" fill="#92400e">{beach_name}</text>')

    meters, px = _scale_bar(meters_per_px)
    y = SVG_HEIGHT - 38
    fact_lines = [
        f'OSM parking objects: {parking_count}',
        f'Mapped steps: {", ".join(mapped_step_counts)}' if mapped_step_counts else 'Mapped steps: none tagged with count',
        'Reviewed route: not curated yet',
    ]
    fact_text = ''.join(f'<text x="0" y="{idx * 22}" font-size="14" fill="#334155">{html.escape(line)}</text>' for idx, line in enumerate(fact_lines, start=1))
    svg.extend([
        f'<g class="scale-bar"><line x1="48" y1="{y}" x2="{48 + px}" y2="{y}" stroke="#111827" stroke-width="4"/><text x="48" y="{y - 10}" font-size="16" fill="#111827">{meters} m</text></g>',
        '<g class="map-legend" transform="translate(650 32)"><rect x="-14" y="-22" width="286" height="138" rx="14" fill="white" opacity="0.88" stroke="#cbd5e1"/><text x="0" y="0" font-size="16" font-weight="800" fill="#111827">Access sketch</text><circle cx="8" cy="24" r="10" fill="#1d4ed8"/><text x="28" y="29" font-size="14" fill="#334155">P = OSM parking</text><line x1="0" y1="50" x2="42" y2="50" stroke="#374151" stroke-width="4" stroke-linecap="round"/><text x="52" y="55" font-size="14" fill="#334155">roads</text><line x1="0" y1="74" x2="42" y2="74" stroke="#16a34a" stroke-width="3" stroke-dasharray="5 6" stroke-linecap="round"/><text x="52" y="79" font-size="14" fill="#334155">paths / steps</text><line class="driving-route" x1="196" y1="50" x2="214" y2="50" stroke="#111827" stroke-width="1" opacity="0.01"/><line class="walking-route" x1="196" y1="74" x2="214" y2="74" stroke="#f97316" stroke-width="1" opacity="0.01"/><circle cx="8" cy="100" r="9" fill="#fb7185" stroke="#be123c" stroke-width="3"/><text x="28" y="105" font-size="14" fill="#334155">stored surf coordinate</text></g>',
        f'<g class="access-facts" transform="translate(650 198)"><rect x="-14" y="-20" width="286" height="96" rx="14" fill="white" opacity="0.88" stroke="#cbd5e1"/><text x="0" y="0" font-size="16" font-weight="800" fill="#111827">Useful OSM facts</text>{fact_text}</g>',
        '<text class="osm-attribution" x="48" y="595" font-size="14" fill="#334155">© OpenStreetMap contributors</text>',
        '<text x="600" y="595" font-size="14" fill="#b45309">Generated from local OSM-derived data · requires manual review</text>',
        '</g>',
        '</svg>',
    ])
    meta = _metadata_from_fixture(map_id, cfg, fixture_path, fixture, warnings)
    return '\n'.join(svg) + '\n', meta


def generate(map_id_filter: str | None = None) -> int:
    configs = load_access_map_configs(CONFIG_DIR)
    if map_id_filter:
        configs = {k: v for k, v in configs.items() if k == map_id_filter}
        if not configs:
            raise SystemExit(f'Unknown access map id: {map_id_filter}')
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    wrote = 0
    for map_id, cfg in configs.items():
        fixture = GENERATED_DIR / f'{map_id}.source.geojson'
        if not fixture.exists():
            warnings = ['No local OpenStreetMap raw/vector fixture found; SVG was not generated to avoid inventing roads, routes, parking, or access restrictions.']
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
            stale_svg = STATIC_DIR / f'{map_id}.svg'
            if stale_svg.exists():
                stale_svg.unlink()
            continue
        svg, meta = render_svg(map_id, cfg, fixture)
        svg_path = STATIC_DIR / f'{map_id}.svg'
        svg_path.write_text(svg, encoding='utf-8')
        validation_warnings = validate_svg(svg_path)
        if validation_warnings:
            meta['warnings'].extend(validation_warnings)
            svg_path.unlink(missing_ok=True)
        else:
            wrote += 1
        (GENERATED_DIR / f'{map_id}.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Processed {len(configs)} access-map configs; wrote {wrote} SVG files. Missing maps remain marked pending; generated maps require manual review.')
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate static WaveWatch SVG access maps from local OpenStreetMap vector fixtures.')
    parser.add_argument('--validate-only', action='store_true', help='Validate existing SVG files instead of generating metadata.')
    parser.add_argument('--map-id', help='Generate only one access map id.')
    args = parser.parse_args()
    if args.validate_only:
        errors = []
        for path in sorted(STATIC_DIR.glob('*.svg')):
            errors.extend(f'{path}: {w}' for w in validate_svg(path))
        if errors:
            raise SystemExit('\n'.join(errors))
        print('Existing access-map SVG validation passed.')
    else:
        raise SystemExit(generate(args.map_id))


if __name__ == '__main__':
    main()
