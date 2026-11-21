# Minimal Chat Incomplete Reply Fix

## Issue

Minimal Chat treated incomplete replies as complete:

- When a model hit `MAX_OUTPUT_TOKENS`, the stream ended with `finish_reason="length"`, but the server always sent a plain `done`. A reasoning model can spend the whole budget on reasoning, so the user could get an empty answer with no explanation.
- If the HTTP stream closed before the server's `done` event (for example, a proxy dropped it), the browser accepted the partial or empty text and stored it in history as a finished assistant turn.

**Root cause:** the server ignored `finish_reason`, and the browser never checked that the final event had arrived.

**Version:** 0.261.067 (feature added in 0.261.066)

## Technical Details

**Files modified**

- `application/minimal_chat/app.py`: records the last non-empty `finish_reason` and sends it as `{"type": "done", "finish_reason": ...}`.
- `application/minimal_chat/static/chat.js`:
  - EOF without `done` is an error ("The reply was interrupted").
  - `finish_reason` of `length` or `content_filter` (or any other value except `stop`) shows a warning.
  - A failed or empty turn is removed from both the screen and history, and the prompt is put back in the input box. A truncated non-empty reply is kept, with a warning shown.
  - A missing `finish_reason` is treated as normal, so endpoints that omit it don't produce false warnings.
- `functional_tests/test_minimal_chat_model_selection.py`: asserts `finish_reason` is passed through for both `stop` and `length`.

**Impact:** limited to the standalone Minimal Chat app. The `done` event gains a field; there are no other API changes.

## Validation

- Functional test passes.
- Browser (Playwright) checks with stubbed streams:

| Case | Before | After |
|------|--------|-------|
| Normal reply | Stored | Stored, no warning |
| `length`, partial text | Stored silently | Stored, warning shown |
| `length`, no text | Empty turn stored | Error, turn dropped, prompt restored |
| Stream closed without `done` | Partial stored silently | Error, turn dropped, prompt restored |
| Server `error` event mid-stream | Partial stored | Error, turn dropped, prompt restored |

In every failure case the next request's history no longer contains the failed turn.
