# Moderation

`/mod` is available to moderators and administrators. Ordinary users and anonymous visitors cannot access it.

## Webcam suggestion queue

Authenticated users can suggest webcam links from `/surf/spots/{slug}`. Suggestions are stored in `webcam_suggestions` with status `pending` and are never displayed publicly until approved.

The moderation page shows:

- spot name,
- suggested title,
- suggested operator name,
- submitted URL,
- submitting username,
- submission timestamp,
- submitter note,
- external review link,
- approval form,
- rejection form,
- moderator note field.

The external review link opens in a new browser tab with `target="_blank" rel="noopener noreferrer"`.

Moderators are reminded to verify:

- the page contains a webcam,
- the page belongs to the camera operator or rights holder,
- the page is not merely an aggregator,
- the camera appears relevant to the selected surf spot,
- the URL is stable enough for users to open,
- the operator name is accurate.

## Approval workflow

Approval is transactional. It creates one `spot_webcams` row, copies the reviewed title/operator/URL, records reviewer and review timestamp, sets the suggestion to `approved`, and links the suggestion through `approved_webcam_id`.

If approval is retried for a suggestion that is already approved, the handler redirects without creating another webcam. This prevents duplicate approved webcam records on double-submit.

## Rejection workflow

Rejecting sets status to `rejected`, records reviewer and timestamp, stores the moderator note, and creates no webcam record. Rejected suggestions are retained for auditability and are not displayed on public spot pages.

## Photo moderation

The `/mod` page includes uploaded-photo moderation. Moderators and administrators can set a photo to `hidden` or restore it to `active`. Hidden photos are preserved on disk and in the database but do not render on the spot page.

Moderator notes are not exposed to ordinary users.
