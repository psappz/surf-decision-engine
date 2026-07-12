# Spot administration

`/adm` is available only to administrators. The current preserved production roles are:

- Patrick: admin
- Loliking: moderator
- David: user

Administrators can open `/adm` from the authenticated surf navigation. The page lists all stored surf spots with name, beach, zone, slug, active recommendation status, difficulty, approved-webcam count, uploaded-photo count, last-modified timestamp and an edit link. Spot edit links use `target="_blank" rel="noopener noreferrer"`.

## Editing surf spots

`GET /adm/spots/{spot_id}` opens the spot editor. `POST /adm/spots/{spot_id}` saves the editable spot fields grouped into identity, location, description, surf characteristics, swell, wind, tide, safety/access, recommendation configuration and access-map sections.

Validation includes:

- CSRF token required for every state-changing request.
- admin role required server-side.
- slug format validation.
- duplicate slug and code rejection.
- latitude range `-90..90` and longitude range `-180..180`.
- numeric optional fields may be blank and remain nullable.
- directional values are stored as degrees; min/max ranges may still wrap around 0/360 where the scoring code expects that behavior.
- failed validation returns the form with field-level errors and does not persist changed values.

Saving a spot updates `updated_at`. The current schema does not yet include a per-spot `updated_by_user_id`, so editor identity is not recorded on the `surf_spots` row.

## Approved webcams from `/adm`

The spot edit page includes a Webcams section. Administrators can add, edit, activate/deactivate and delete approved webcam links. Reordering is controlled by the `sort_order` field on each webcam row. Approved links must point to the operator, owner, rights holder, municipality, surf school, hotel, bar or official partner operating the camera; aggregator pages are excluded.

## Photo moderation shortcut

The spot edit page shows uploaded photos for the spot. Hiding/restoring uploaded photos is performed under `/mod` so moderators and administrators share one moderation queue.
