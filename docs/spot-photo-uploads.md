# Spot photo uploads

Authenticated users can upload photos on `/surf/spots/{slug}`. Anonymous users cannot upload.

## Upload UI

The spot page contains a progressive-enhancement drag-and-drop area with a real file input. It works without JavaScript and gains drag-over styling plus selected filename display when JavaScript is available. Clicking the drop area opens the native file chooser. The label text is:

```text
Drag images here
or
Click to select images
```

## Formats and limits

Allowed input formats:

- JPEG
- PNG
- WebP

Rejected formats include SVG, GIF, PDF, HTML, XML, executables, malformed images and files whose content does not decode as an allowed image type.

Configured defaults:

- maximum files per upload: `10`
- maximum size per original file: `15 MB`
- maximum total request size / Caddy limit: `60 MB`

Environment variables:

- `MEDIA_ROOT`
- `MAX_UPLOAD_FILES`
- `MAX_UPLOAD_FILE_MB`
- `MAX_UPLOAD_TOTAL_MB`

## Processing

Uploads are processed before they become visible:

1. Decode and validate with Pillow.
2. Reject unsupported or malformed images.
3. Normalize EXIF orientation.
4. Strip EXIF and metadata by writing a new image.
5. Convert to RGB where needed.
6. Create `display.webp` with maximum long edge 2000 px.
7. Create `thumbnail.webp` with maximum long edge 500 px.
8. Store deterministic metadata in `spot_photos`.
9. Use generated UUID paths, never user-supplied final filenames.

## Storage

Production uses a persistent Docker volume mounted at:

```text
/data/media
```

The application stores paths relative to `MEDIA_ROOT`:

```text
spots/{spot_id}/{image_uuid}/display.webp
spots/{spot_id}/{image_uuid}/thumbnail.webp
```

Media are served by the app through `/media/{relative_path}` with `X-Content-Type-Options: nosniff` and fixed safe image content types. Directory traversal is rejected. Images are not stored in PostgreSQL.

## Photo status

`spot_photos.status` supports:

- `active`
- `hidden`
- `deleted`

This version makes authenticated uploads active immediately. Moderators and administrators can hide or restore photos under `/mod`. Hidden photos remain stored and associated with the uploader but are not displayed on the spot page.
