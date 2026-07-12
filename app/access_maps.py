from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / 'data' / 'access-maps'
GENERATED_DIR = ROOT / 'data' / 'access-maps-generated'
STATIC_DIR = ROOT / 'app' / 'static' / 'access-maps'

VALID_STATUSES = {'missing', 'generated', 'needs_review', 'verified', 'outdated'}

@dataclass(frozen=True)
class AccessMapConfig:
    id: str
    title: str
    spot_slugs: tuple[str, ...]
    notes: tuple[str, ...]
    verified: bool = False


def _scalar(value: str) -> Any:
    value = value.strip()
    if value == 'null':
        return None
    if value == 'false':
        return False
    if value == 'true':
        return True
    return value.strip('"\'')


def load_access_map_configs(config_dir: Path = CONFIG_DIR) -> dict[str, AccessMapConfig]:
    configs: dict[str, AccessMapConfig] = {}
    if not config_dir.exists():
        return configs
    for path in sorted(config_dir.glob('*.yaml')):
        text = path.read_text(encoding='utf-8')
        map_id = re.search(r'^id:\s*(.+)$', text, re.M)
        title = re.search(r'^title:\s*(.+)$', text, re.M)
        verified = re.search(r'^verified:\s*(.+)$', text, re.M)
        slugs = _list_block(text, 'spot_slugs')
        notes = _list_block(text, 'notes')
        if not map_id or not title:
            raise ValueError(f'{path} must define id and title')
        configs[map_id.group(1).strip()] = AccessMapConfig(
            id=map_id.group(1).strip(),
            title=title.group(1).strip(),
            spot_slugs=tuple(slugs),
            notes=tuple(notes),
            verified=bool(_scalar(verified.group(1))) if verified else False,
        )
    return configs


def _list_block(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    out: list[str] = []
    in_block = False
    for line in lines:
        if re.match(rf'^{re.escape(key)}:\s*$', line):
            in_block = True
            continue
        if in_block:
            if line and not line.startswith(' '):
                break
            m = re.match(r'^\s*-\s*(.+?)\s*$', line)
            if m:
                out.append(_scalar(m.group(1)))
    return out


def spot_to_access_map(configs: dict[str, AccessMapConfig] | None = None) -> dict[str, AccessMapConfig]:
    configs = configs or load_access_map_configs()
    mapping: dict[str, AccessMapConfig] = {}
    for cfg in configs.values():
        for slug in cfg.spot_slugs:
            if slug in mapping:
                raise ValueError(f'spot slug {slug} is assigned to multiple access maps')
            mapping[slug] = cfg
    return mapping


def osm_link(latitude: float, longitude: float, zoom: int = 16) -> str:
    return f'https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map={zoom}/{latitude}/{longitude}'


def metadata_for(map_id: str) -> dict[str, Any] | None:
    path = GENERATED_DIR / f'{map_id}.json'
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def access_map_context(spot) -> dict[str, Any]:
    cfg = spot_to_access_map().get(spot.slug)
    if not cfg:
        return {'status': 'missing', 'config': None, 'asset_exists': False, 'notes': ['No access-map configuration is assigned to this spot.']}
    asset = f'/static/access-maps/{cfg.id}.svg'
    asset_path = STATIC_DIR / f'{cfg.id}.svg'
    status = getattr(spot, 'access_map_status', None) or ('needs_review' if asset_path.exists() else 'missing')
    if status not in VALID_STATUSES:
        status = 'missing'
    meta = metadata_for(cfg.id)
    warnings = []
    if meta:
        warnings = list(meta.get('warnings') or [])
    if not asset_path.exists():
        warnings.append('Access sketch is not generated yet because local OpenStreetMap vector data has not been provided.')
    return {
        'config': cfg,
        'asset': asset,
        'asset_exists': asset_path.exists(),
        'status': status,
        'metadata': meta,
        'warnings': warnings,
        'notes': list(cfg.notes),
        'external_navigation_url': getattr(spot, 'external_navigation_url', None) or spot.maps_url,
        'osm_url': osm_link(spot.latitude, spot.longitude),
        'alt': f'Access sketch from the regional road to {spot.name}, showing final vehicle access, parking, walking access and surf zones.',
    }
