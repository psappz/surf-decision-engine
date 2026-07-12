from __future__ import annotations

import argparse
from pathlib import Path

from app.access_maps import GENERATED_DIR, load_access_map_configs
from app.seed_data import SPOTS

QUERY_RADIUS_METERS = 1800

SPOTS_BY_SLUG = {spot['slug']: spot for spot in SPOTS}


def overpass_query(latitude: float, longitude: float, radius_m: int = QUERY_RADIUS_METERS) -> str:
    return f'''[out:json][timeout:60];
(
  way(around:{radius_m},{latitude},{longitude})["highway"];
  way(around:{radius_m},{latitude},{longitude})["amenity"="parking"];
  node(around:{radius_m},{latitude},{longitude})["amenity"="parking"];
  way(around:{radius_m},{latitude},{longitude})["natural"="beach"];
  way(around:{radius_m},{latitude},{longitude})["natural"="coastline"];
  relation(around:{radius_m},{latitude},{longitude})["natural"="beach"];
);
out body geom;
'''


def write_queries(map_id_filter: str | None = None, radius_m: int = QUERY_RADIUS_METERS) -> int:
    configs = load_access_map_configs()
    if map_id_filter:
        configs = {k: v for k, v in configs.items() if k == map_id_filter}
        if not configs:
            raise SystemExit(f'Unknown access map id: {map_id_filter}')
    query_dir = GENERATED_DIR / 'overpass-queries'
    query_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    for map_id, cfg in configs.items():
        anchor = next((SPOTS_BY_SLUG.get(slug) for slug in cfg.spot_slugs if slug in SPOTS_BY_SLUG), None)
        if not anchor:
            continue
        query_path = query_dir / f'{map_id}.overpass.ql'
        query_path.write_text(overpass_query(float(anchor['latitude']), float(anchor['longitude']), radius_m), encoding='utf-8')
        wrote += 1
    print(f'Wrote {wrote} Overpass query files under {query_dir}. Run them manually outside app runtime, then convert reviewed OSM output into *.source.geojson fixtures.')
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description='Prepare offline Overpass query files for WaveWatch access-map source acquisition.')
    parser.add_argument('--map-id', help='Prepare only one access map id.')
    parser.add_argument('--radius-m', type=int, default=QUERY_RADIUS_METERS, help='Query radius in meters around the seeded spot coordinate.')
    args = parser.parse_args()
    raise SystemExit(write_queries(args.map_id, args.radius_m))


if __name__ == '__main__':
    main()
