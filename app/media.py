from __future__ import annotations

import ipaddress
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

SAFE_IMAGE_FORMATS = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}
SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
HTML_RE = re.compile(r'<\s*(?:script|iframe|html|body|a\s|img\s)', re.I)


@dataclass
class ProcessedImage:
    display_rel: str
    thumbnail_rel: str
    stored_mime_type: str
    width: int
    height: int
    file_size: int


def validate_slug(value: str) -> bool:
    return bool(SLUG_RE.fullmatch(value or ''))


def _host_is_private(host: str | None) -> bool:
    if not host:
        return True
    h = host.strip('[]').lower()
    if h in {'localhost'} or h.endswith('.localhost'):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        return False


def validate_webcam_url(url: str, *, allow_http: bool = False) -> str:
    cleaned = (url or '').strip()
    if not cleaned or len(cleaned) > 1000 or HTML_RE.search(cleaned):
        raise ValueError('Enter a valid direct webcam operator URL.')
    parsed = urlparse(cleaned)
    if parsed.scheme not in {'https', 'http'}:
        raise ValueError('Webcam URL must use https://, or explicit http:// operator fallback.')
    if parsed.scheme == 'http' and not allow_http:
        raise ValueError('HTTP webcam URLs require explicit administrator approval.')
    if _host_is_private(parsed.hostname):
        raise ValueError('Localhost and private-network webcam URLs are not allowed.')
    if not parsed.netloc:
        raise ValueError('Enter a complete webcam URL including the host.')
    return cleaned


def csrf_or_403(request, token: str | None) -> None:
    expected = getattr(request.state, 'csrf', None)
    if not expected or token != expected:
        raise HTTPException(403, 'Invalid CSRF token')


def media_root() -> Path:
    return Path(__import__('os').getenv('MEDIA_ROOT', 'media')).resolve()


def media_response_path(rel_path: str) -> Path:
    root = media_root()
    candidate = (root / rel_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(404)
    if not candidate.is_file():
        raise HTTPException(404)
    return candidate


async def process_spot_photo(upload: UploadFile, spot_id: int, *, max_file_bytes: int = 15 * 1024 * 1024) -> ProcessedImage:
    raw = await upload.read()
    if not raw or len(raw) > max_file_bytes:
        raise ValueError('Image is empty or larger than the configured per-file limit.')
    ident = uuid.uuid4().hex
    rel_dir = Path('spots') / str(spot_id) / ident
    target_dir = media_root() / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        from io import BytesIO
        with Image.open(BytesIO(raw)) as src:
            src.verify()
        with Image.open(BytesIO(raw)) as src:
            if src.format not in SAFE_IMAGE_FORMATS:
                raise ValueError('Only JPEG, PNG and WebP images are allowed.')
            img = ImageOps.exif_transpose(src)
            if img.mode not in {'RGB', 'L'}:
                img = img.convert('RGB')
            elif img.mode == 'L':
                img = img.convert('RGB')
            display = img.copy(); display.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
            thumb = img.copy(); thumb.thumbnail((500, 500), Image.Resampling.LANCZOS)
            display_path = target_dir / 'display.webp'
            thumb_path = target_dir / 'thumbnail.webp'
            display.save(display_path, 'WEBP', quality=86, method=6)
            thumb.save(thumb_path, 'WEBP', quality=82, method=6)
            return ProcessedImage(
                display_rel=str(rel_dir / 'display.webp'),
                thumbnail_rel=str(rel_dir / 'thumbnail.webp'),
                stored_mime_type='image/webp',
                width=display.width,
                height=display.height,
                file_size=display_path.stat().st_size,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        # Remove partial output for rejected images.
        for p in target_dir.glob('*') if target_dir.exists() else []:
            p.unlink(missing_ok=True)
        try:
            target_dir.rmdir()
        except OSError:
            pass
        raise ValueError(str(exc) or 'Malformed image upload.')
