# Member 1: local privacy validation

This checklist exercises the Gemma privacy workflow without depending on Member 3's platform integration. Use synthetic text only. The smoke script talks to the loopback PrivacyPal backend, reviews a draft, cancels the workflow, and clears its temporary session. It does not approve a request or call the configured answer provider.

## Before you start

1. From the repository root, start Ollama and confirm `gemma4:e4b` is available with `ollama list`.
2. Start the backend and frontend as described in [LOCAL_SETUP.md](../LOCAL_SETUP.md).
3. Keep answer-provider settings unset for this local review run. The smoke script never approves or sends, but leaving the provider unset also keeps the UI's send control disabled.
4. Use a second PowerShell window at the repository root to run the smoke script:

   ```powershell
   python backend/scripts/gemma_privacy_smoke.py
   ```

   To use a different loopback backend port:

   ```powershell
   python backend/scripts/gemma_privacy_smoke.py --base-url http://127.0.0.1:8001
   ```

The script reports each check without printing the synthetic draft or fixture values. It exits with a nonzero status and a short safe error if the backend or Gemma workflow fails. It only accepts a loopback HTTP backend URL.

## Review the flow in the browser

Run a second pass through the UI so you can judge readability and make manual observations. Use this fabricated text:

```text
Synthetic workshop begins at 10 AM in Lab 4.
Registration contact: test.person@example.test.
Fixture-only credential: Password=FAKE_NOT_A_REAL_CREDENTIAL_12345.
Unrelated note: the demo printer needs paper.
```

Ask: **“When does the synthetic workshop begin?”** Then inspect the exact draft and findings before cancelling.

| Check | Expected observation |
|---|---|
| Relevant selection | The workshop time is retained; the unrelated printer note is omitted. |
| Sensitive findings | The fake email is masked if it is included. The fake credential must never appear in an outbound draft. |
| Review explanation | Findings describe the category and action without exposing the original value. |
| Residual review | The UI shows whether Gemma found contextual risk or the deterministic scan found a remaining identifier. A clear status is not a guarantee of anonymity. |
| Edit and recheck | Editing increments the draft version, clears acknowledgment, and runs the required checks again. |
| Cancel | Cancel the workflow. Do not approve or configure a real provider for this exercise. |

## Edge-case exercise matrix

Repeat in a fresh session with fabricated variations. Do not use a real document or real credential.

| Variation | What to check |
|---|---|
| Relevant sentence plus unrelated personal details in separate sentences | Unrelated sentences should not appear merely because they share the document. Check whether question wording selects the intended fact. |
| Similar identifier-looking value that is not personal data, such as `Order code: 123-456-7890` | It should not be mislabeled as a phone when clearly labeled as an order code. Record other false positives and whether the reason/action shown makes sense. Do not choose “keep” for a credential or other high-risk value. |
| Fake email or phone number in relevant context | The raw value should be absent from the draft; check placeholder clarity and whether the answer would still be useful. |
| Fake password, API key, or valid test card number in relevant context | The value must be omitted or the draft blocked; approval must remain unavailable while a high-risk pattern remains. |
| Question unrelated to all document content | The workflow should fail closed or indicate that relevant content could not be safely selected; do not accept a guessed answer. |
| Edited draft containing a fake credential | Review should become blocked, acknowledgment should be cleared, and there should be no way to approve it. |
| Cancel after review | The review should close; no answer-provider request should occur. |

Keep notes with only synthetic input labels and outcomes. Do not paste source text, raw findings, drafts, credentials, or screenshots with private content into issue trackers or chat.

## Automated checks

From the repository root, run the deterministic backend suite:

```powershell
python -m pytest backend/tests
```

These tests use fake model/provider adapters and synthetic fixtures; they do not require Ollama or a network connection. The live Ollama check is opt-in and must be run separately with the selected local model available.

## Record observations

### Run record — 2026-10-17

```text
Date / branch: 2026-10-17 / avan (reported from the OneDrive checkout)
Ollama model tag: gemma4:e4b
Scenario label: synthetic workshop smoke check and browser review
Expected behavior: keep the workshop time, exclude unrelated and synthetic sensitive values, complete local review, and cancel without provider send
Observed behavior: smoke script reported all four PASS checks; residual review status was needs_review. User confirmed completing the browser review, but did not report the exact draft or warning details.
False positive or missed pattern: deterministic check found an order-code value formatted like a phone was mislabeled; phone detection now ignores values directly labeled as order/tracking/reference identifiers. Other false positives and missed patterns remain unassessed.
Was the exact draft understandable after masking? (yes/no + brief note): not reported for the browser run; synthetic relevant email and phone values were masked by deterministic checks.
Did edit trigger a fresh check? (yes/no): user completed the browser review, but did not report this detail; an existing API regression test covers invalidation/recheck on edit.
Did cancel leave the workflow unsent? (yes/no): yes in the smoke check; an automated API regression test checks that cancellation results in zero mock-provider calls.
Follow-up file or issue: try the remaining cases in the UI and note the exact visible warning/edit outcomes; detector checks are heuristics, not a guarantee
```

### Automated edge-case follow-up — 2026-10-17

```text
Synthetic scenarios checked: phone-shaped order code; relevant synthetic email and phone; unrelated question; edited draft with a synthetic credential; cancellation with provider-call spy.
Outcome: regression tests cover all scenarios above. Phone-shaped order codes are no longer reported as phone findings; relevant email/phone values are masked; irrelevant content fails closed; credential edits are blocked; cancellation makes no provider call.
Backend suite: 54 passed, 0 failed (python -m pytest backend/tests -q).
Repository compatibility fixes: migrated the obsolete approval-flow test from the removed /requests API to the current workflow API, and aligned unknown-session expectations with the current SESSION_EXPIRED response.
Live UI observations: not newly performed in this run; see the earlier user-reported browser review above.
```

Use the template below for each additional scenario. Keep the run record factual; do not infer observations that were not captured.

Copy this small template into your team notes and fill it using synthetic scenario names only:

```text
Date / branch:
Ollama model tag:
Scenario label:
Expected behavior:
Observed behavior:
False positive or missed pattern:
Was the exact draft understandable after masking? (yes/no + brief note):
Did edit trigger a fresh check? (yes/no):
Did cancel leave the workflow unsent? (yes/no):
Follow-up file or issue:
```

Pattern checks are limited heuristics. A clean result does not prove that all identifying information was found or that the remaining request is anonymous; review the exact draft yourself before any real external send.
