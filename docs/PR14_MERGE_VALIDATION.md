# Sarvam integration and PR #14 conflict resolution

Merged current `main` (`b951a05e58334481835fa6e764679b455169cc7e`) into the Sarvam branch (`0c8a1e3263bfbceae23883e36ac356b5686e8134`). Preserve the current liquid-glass UI, saved conversations, Gemma analysis improvements, session ownership/concurrency checks, exact-request approval, and answer withholding.

## Integration

- Optional Sarvam answer provider is bound to each reviewed workflow; approval cannot redirect it. It receives the existing grounding instructions and exact approved user message.
- Draft translation is independently consented, versioned, checked against source identities, and returned as a preview. Applying it invokes the standard local edit/recheck flow. Stale results and concurrent approval/edit are rejected.
- Audio upload and microphone dictation return a question for review, without auto-submitting it. Recordings stop after 30 seconds. Consent is reset for each new audio selection, and microphone tracks are stopped on completion or component cleanup.
- Answer translation and WAV speech require independent consent and the digest of the exact answer returned in the active session. Completed document/workflow content is still released. A new document/question or session cleanup revokes the digest.
- Sarvam settings use the same backend-file/process precedence as existing settings; keys never reach the frontend. Existing Groq behavior remains available.
- The speech gateway response limit is separately bounded to 5 MiB; ordinary responses stay at 512 KiB, and hosted uploads retain the existing 4 MiB limit.
- Provider response bytes, text, placeholders, base64 and audio format are validated. No automatic provider fallback or retry was added.

The generated API definitions in the published `sarvamai` 0.1.37 wheel were consulted to verify the translation fields, `saaras:v4` transcription model, and `bulbul:v4-flash` TTS request with `text`, `language_code`, and `output_audio_codec: "wav"`. The SDK remains optional; the app uses HTTPX.

## Validation

- Backend: `cd backend && ../.venv/bin/python -m pytest -q` — 255 passed; one existing upstream TestClient deprecation warning.
- Frontend: `cd frontend && npm test` — 88 passed, zero skipped.
- Frontend: `cd frontend && npm run build` — passed.
- Dependency consistency: `.venv/bin/python -m pip check` — passed.
- `git diff --check` — passed.
- Headless Chromium with synthetic local adapters: real PNG/OCR ingestion; Sarvam provider selection; consented audio-file transcription without question submission; draft translation and local recheck; exactly one approved answer call with the exact translated draft; answer translation; playable WAV audio; microphone start/stop; reset consent; mobile controls and saved-history navigation; no JavaScript runtime errors.
- Regression tests cover final identity checks, changed/dropped/duplicated placeholders, credential/answer withholding, one-use approval, missing consent, stale versions, clear during translation, oversized responses, speech proxy limits, exact-answer matching, and no provider fallback.

## Remaining runtime prerequisites

No live Sarvam call or AWS deployment was performed. `SARVAM_API_KEY` was absent and documentation-site access was denied by the environment's network policy. Configure the key securely on the backend, allow HTTPS to `api.sarvam.ai`, restart the backend, and reload the UI for live use. Local Gemma remains required for initial and edited-request privacy checks. Multilingual detection, translation quality, and generated speech are not guaranteed by mocked tests; review provider/model availability and results before a production release.
