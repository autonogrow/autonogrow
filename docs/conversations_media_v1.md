# Conversations Media V1

## Audited flow

- Instagram webhook parsing keeps the provider event in `ConversationMessage.raw_payload_json`; attachment metadata lives under `message.attachments`.
- WhatsApp webhook parsing normalizes non-text messages before the inbox queue. The inbox processor now persists those events as ordinary inbound `ConversationMessage` rows instead of ignoring them.
- Manual/internal conversations have no inbound attachment source in the current architecture and remain text-only.
- `ConversationMessage` has no attachment table. The existing JSON payload is sufficient for V1, so this change adds no schema or Alembic revision.

## Normalized API contract

Conversation message serialization exposes `attachments` with these public fields:

```json
{
  "id": "1",
  "kind": "image | video | audio | document | unknown",
  "mime_type": "image/jpeg",
  "filename": "imagen.jpg",
  "size_bytes": 12345,
  "caption": "optional text",
  "status": "available | unavailable | unsupported",
  "source": "instagram | whatsapp",
  "access_url": "/api/admin/businesses/.../content",
  "thumbnail_url": "/api/admin/businesses/.../content?variant=thumbnail"
}
```

Provider URLs, media IDs and credentials are private inputs and are never serialized. `body_is_attachment_fallback` lets the UI suppress a generated media label while preserving genuine text and captions. Historical rows that only contain `[Adjunto recibido]` and no usable metadata continue to render that text; no attachment is invented.

## Secure access

`GET /api/admin/businesses/{business_slug}/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}/content` inherits Admin/Staff business access and validates the business, conversation, message and attachment chain. Cross-tenant or mismatched direct IDs return 404.

Instagram media is fetched only from a fixed HTTPS Meta CDN allowlist. WhatsApp media IDs are resolved against the fixed Graph API origin with the business integration token, then the returned URL is checked against the same allowlist. Redirects are disabled, responses are bounded to 25 MiB and provider URLs/tokens are not logged. Active HTML and SVG are never served inline; filenames are sanitized and response headers include `nosniff` and a sandbox CSP.

Provider expiry, denial, timeout, malformed metadata and unsupported types affect only the attachment. The thread remains usable and the UI replaces failed media with `Adjunto no disponible` without retrying indefinitely.

## UI and behavior

- Images load lazily as bounded previews and open in an accessible in-workspace viewer with backdrop close, Escape, focus trap and focus restoration.
- Video and audio use native controls without autoplay and with conservative preload.
- Documents and unknown files use wrapping file cards and explicit accessible actions.
- Media-only, text-plus-media and captions share the existing message bubble and direction/timestamp semantics.
- Inbox previews use the normalized media kind when the last body is a generated fallback.
- Inbound media follows the existing `needs_reply`, last-inbound and automation paths. No OCR, transcription, Customer Memory extraction or Growth semantic change is introduced.
- The composer remains text-only. Outbound multimedia is explicitly outside V1.
