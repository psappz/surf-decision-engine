# Webcam links

Surf Decision Engine stores approved surf-spot webcam links in `spot_webcams`.

## Operator-link-only policy

Approved webcam links must point directly to the organization operating or owning the camera or to an official partner page for that camera. Examples include surf schools, municipalities, hotels, bars, beach operators and camera-rights holders.

Do not approve generic webcam aggregators as surf-spot webcams. Windy, Meteoblue, WorldCam, PortugalWebcams, Surf-Forecast, Surfline or similar services are not stored unless the specific link genuinely points to a camera operated by that organization.

## Why aggregators are excluded

The app presents webcams as trusted operator-owned external links. Aggregators may contain stale embeds, unrelated cameras, tracking-heavy pages or generic map searches. They also do not prove who owns or operates the camera. For that reason the previous `Nearby webcam check` behavior and default Windy link were removed and not migrated into `spot_webcams`.

## URL validation

Approved links and user suggestions use the same safety checks:

- `https://` is required by default.
- `http://` is accepted only when an administrator explicitly chooses the HTTP fallback.
- `javascript:`, `data:`, `file:` and malformed URLs are rejected.
- localhost, loopback, link-local and private-network hosts are rejected.
- obvious embedded HTML is rejected.
- submitted URLs are not fetched synchronously while rendering pages.

## Display behavior

`/surf/spots/{slug}` shows a `Webcams` section. Only active approved webcam records are displayed. Each link opens in a new tab with:

```html
target="_blank" rel="noopener noreferrer"
```

Surf Decision Engine does not embed streams, proxy pages, cache webcam pages, show screenshots or perform automated webcam-image analysis.
