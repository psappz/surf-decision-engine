# Access maps

## Why proprietary map imagery is not used

Surf Decision Engine access sketches must not use, copy, trace, screenshot, download, or visually reproduce Google Maps, Google satellite imagery, Google Street View, Apple Maps, Bing Maps, or other proprietary map products. The SVGs are intended to be reproducible vector sketches derived from legally reusable geographic data.

## OpenStreetMap attribution and licensing

The intended source is OpenStreetMap raw vector data, licensed under the Open Data Commons Open Database License (ODbL). Generated SVGs that use OSM-derived data must visibly include:

`© OpenStreetMap contributors`

The attribution belongs inside the SVG in a discreet readable lower corner.

## Raw data sources

The generator is designed for local, developer-operated raw vector input. In this local-only environment no OSM extract or GeoJSON fixture is currently present, and public Overpass/OSRM/openrouteservice calls are not permitted. Therefore the current implementation records missing-data metadata and does not invent access maps.

Accepted future inputs:

- a bounded Overpass result saved as deterministic GeoJSON,
- a regional OSM `.pbf` extract converted into a bounded GeoJSON subset,
- locally stored route geometries derived from OSM data,
- reviewed manually curated coordinates with OSM object IDs and retrieval dates.

Raster OSM tiles are not acceptable as source material.

## Route providers

The preferred production workflow is offline or developer-operated route extraction using OSM data. Public shared API services may only be used during generation and must never be called during normal page rendering or automated tests.

## Source acquisition commands

Prepare one Overpass query per configured access map without calling the network from the app:

```bash
python -m app.tools.prepare_access_osm_queries
# or one spot:
python -m app.tools.prepare_access_osm_queries --map-id odeceixe --radius-m 1800
```

This writes `.overpass.ql` files under `data/access-maps-generated/overpass-queries/`. Run those queries manually/developer-side against Overpass or a local OSM stack, save the JSON response, then convert it locally:

```bash
python -m app.tools.convert_overpass_access_fixture /path/to/odeceixe.overpass.json --map-id odeceixe
```

The converter writes `data/access-maps-generated/<id>.source.geojson`. It imports roads, tracks, paths, parking, beach and coastline features that are present in the OSM response. Driving and walking route features still need review/curation before the SVG should be treated as route guidance.

## Generation command

```bash
python -m app.tools.generate_access_maps
# or one map:
python -m app.tools.generate_access_maps --map-id odeceixe
```

The command loads `data/access-maps/*.yaml`, checks for local OSM-derived fixtures under `data/access-maps-generated/*.source.geojson`, writes audit metadata under `data/access-maps-generated/*.json`, and refuses to create SVGs when the legal raw data source is missing. When a local GeoJSON fixture exists, it renders `app/static/access-maps/<id>.svg` with OSM attribution and `requires_manual_review: true` metadata.

## Configuration format

Each file in `data/access-maps/` defines one physical access sketch and the surf-spot slugs sharing it. Coordinates are nullable until verified against open geographic sources. Required sections include destination, parking, road entry, driving route, optional walking route, surf zones, viewport preferences, notes, and verification fields.

## Manual verification workflow

1. Obtain a local OSM-derived vector subset for the map area.
2. Record bounding box, OSM object IDs, retrieval date, and route request parameters.
3. Generate the SVG locally.
4. Review road suitability, access tags, parking, walking continuation, cliffs, stairs, gates, unpaved tracks, and route endpoint distance.
5. Leave `requires_manual_review: true` until a human has reviewed the generated sketch.
6. Do not mark `verified` unless the route has been checked against open geographic data; do not claim physical inspection unless it happened.

## Updating one map

Update the matching `data/access-maps/<id>.yaml`, replace or refresh the local OSM-derived fixture, run the generation command, inspect `app/static/access-maps/<id>.svg`, and update `docs/access-map-review.md`.

## Adding another beach

Create a new YAML config, assign one or more spot slugs, add a local OSM-derived fixture, generate the SVG, and add a review section. Avoid duplicate maps for surf zones sharing the same physical access route.

## Map-status meanings

- `missing`: no reviewed SVG asset exists.
- `generated`: SVG exists but review state is not final.
- `needs_review`: SVG exists or metadata exists and requires human review.
- `verified`: reviewed against open data and approved for display.
- `outdated`: source data or access conditions may have changed.

## Known limitations

The current repository has configuration, model fields, UI, generator entry point, and audit metadata, but no legally sourced local OSM vector extract. This prevents honest generation of road, parking, path, coastline, or access-restriction geometry.

## Stale-map detection

Generation metadata records retrieval timestamps, route source, source-coordinate hashes, and generator version. A map is stale when the fixture retrieval date, route provider/version, config, or generator version no longer matches the reviewed asset.

## Not navigation or safety advice

Access sketches are orientation aids only. They are not substitutes for navigation apps, road signs, local restrictions, weather/surf safety checks, tide checks, or direct visual inspection.
