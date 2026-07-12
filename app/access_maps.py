from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / 'data' / 'access-maps'
GENERATED_DIR = ROOT / 'data' / 'access-maps-generated'
STATIC_DIR = ROOT / 'app' / 'static' / 'access-maps'

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
