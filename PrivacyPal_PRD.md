> PRD TEMPLATE

# Product Requirements Document

## 1. Product Overview

**Product Name:**

PrivacyPal

**One-Line Description:**

PrivacyPal is a local-first AI privacy proxy where Gemma 4 uses secure tools to minimize sensitive files before sending approved content to an AI and returning its answer in the same chat.

**Product Type:**

Local-first web app and AI privacy assistant.

**Primary Platform:**

Desktop

---

## 2. Problem

**What problem are we solving?**

People want AI help with sensitive files, but sending originals can expose personal details, passwords, or API keys, while manual redaction is slow and can remove information the AI needs to answer.

**Why does this problem matter?**

It matters because people need AI’s help with payslips, medical reports, bank statements, and work documents, but sharing those files can expose private information or credentials. If protecting data means tedious manual redaction—or losing details needed for an answer—people may avoid useful AI tools altogether.

**How are users solving this today?**

AI provider privacy settings let users manage chat history, retention, and whether eligible chats can be used to improve models. But users still send their sensitive content to that provider.

Local AI tools, such as Ollama, run models on the user’s computer, keeping prompts local. Users have to use a local model, which may not match their preferred cloud AI’s capabilities.

PII detection tools, such as Presidio, find and anonymize personal information. Users or developers still need to connect that to a useful AI conversation.

AI gateways and proxies can redact sensitive details before forwarding a request and restore placeholders in the reply. These are a close alternative, so PrivacyPal shouldn’t claim that no other tools do this.

---

## 3. Goal

**Primary Goal:**

- Our primary goal is to help people get useful AI answers about sensitive files while minimizing the private information shared with cloud AI.
**Secondary Goals:**

- Use Gemma 4 meaningfully, letting it drive the local privacy workflow through approved tool calls.
- Keep users in control by showing exactly what will be shared and asking before sending.
- Preserve the information the AI needs, so privacy protection doesn’t make its answer useless.
- Support PDFs and scanned images, while being clear about which formats are tested.
- Check the sanitized request for sensitive details that may remain and avoid storing raw file contents in logs.

---

## 4. Target Users

### User Type 1

**Name:**

Individuals

**Description:**

- People who want AI help with sensitive documents without exposing unnecessary personal information.lis
**Needs:**

- Get useful AI answers from sensitive documents.
- Protect personal details, passwords, and API keys.
- Keep the information needed for an accurate answer.
- See and approve exactly what is shared with the AI.
- Avoid manually redacting, downloading, and re-uploading files.
**Pain Points:**

- -They worry that uploading private files could expose personal information, passwords, or API keys.
- They can’t easily see what information an AI service receives.
- Manually finding and redacting sensitive details takes time and can miss things.
- Redacting too much can remove facts the AI needs to answer.
- Downloading a sanitized file and uploading it again makes the process tedious.

---

## 5. User Stories

> As a [user],
> I want to [action]
> so that [outcome].
**Examples:**

- As a user, I want to attach a document or image and ask a question about it in the same chat, so that I don’t have to download and re-upload a sanitized copy.
- lAs a user, I want Gemma to read the file and decide which details matter to my question, so that the AI can answer without receiving the whole file.
- As a user, I want Gemma to find sensitive details and choose what to mask, remove, or keep, so that useful facts remain while private information is protected.
- As a user, I want passwords, API keys, and other high-risk secrets blocked from being sent, so that they cannot accidentally leave my device.
- As a user, I want to review the exact information PrivacyPal plans to send and approve or cancel it, so that I stay in control of what the external AI receives.
- As a user, I want PrivacyPal to check the approved request for details that could still identify me, so that I can catch privacy risks before sending.
- As a user, I want to receive the AI’s answer in the same chat, so that I can use the result without switching between tools.
- As a user, I want the answer to show which parts of my file it used, so that I can check that the response is grounded in the right information.
- As a user, I want PrivacyPal to tell me when it cannot read or safely process a file, so that I’m not given a misleading answer or left unsure what was shared.

---

## 6. Core Features

### Feature 1 — File upload and reading

**Purpose:** Let a user ask questions about a file without copying its contents into another AI chat.

**User flow:** The user uploads a supported file, waits for PrivacyPal to read it, then asks a question in the chat.

**Inputs:** PDF, image, or pasted text; the user’s question.

**Outputs:** Extracted text or image content ready for local analysis; a clear status such as “Ready,” “Couldn’t read,” or “Unsupported file.”

**Acceptance criteria:**
- The user can attach a supported file and ask about it in the same conversation.
- The app tells the user when reading is complete.
- The original file remains unchanged.
- The app shows a useful error when a file cannot be read.

**Edge cases:** Empty or corrupted files; very large files; password-protected PDFs; blurry or rotated scans; unsupported formats.

### Feature 2 —Local Gemma analysis and tool use

**Purpose:** Make Gemma an active part of the privacy workflow. It reads the file and question, decides what actions are needed, and calls approved tools to carry them out.

**User flow:** After upload and question entry, Gemma analyzes the content and requests actions such as scanning for sensitive details, marking text to mask, or building a minimized request. PrivacyPal checks each tool call before executing it.

**Inputs:** File content, user question, approved tool list, and analysis rules.

**Outputs:** Tool calls and their results; a draft of the information needed to answer the question.

**Acceptance criteria:**
- Gemma runs locally for file analysis.
- Gemma can call only the tools PrivacyPal explicitly allows.
- The app validates tool arguments before running them.
- Tool activity is visible to the user in understandable language.
- Gemma cannot send data to an external AI directly.

**Edge cases:** Gemma requests an unknown tool; supplies invalid arguments; makes no tool call; gives conflicting instructions; or the local model is unavailable.

### Feature 3. Sensitive information detection

**Purpose:** Find details that should not be shared, including information that needs context to identify.

**User flow:** Gemma and deterministic checks scan the file. PrivacyPal shows detected items and where they came from.

**Inputs:** File content and extracted text or image details.

**Outputs:** Findings such as names, addresses, phone numbers, account details, passwords, API keys, and other identified sensitive content, with locations and confidence where available.

**Acceptance criteria:**
- Findings include the matched text or a masked preview and its location.
- High-risk secrets such as passwords and API keys are marked to block from sharing.
- The user can inspect or correct findings before approval.
- A failed scan is shown as a failure, not as a clean result.

**Edge cases:** A detector misses a detail; the same detail appears multiple times; a false positive is found; OCR misreads a value; or sensitive information is embedded in an image.

###  Feature 4. Question-aware information selection

**Purpose:** Keep the facts needed to answer the user’s question while reducing unrelated disclosure.

**User flow:** Gemma compares the question with the file, identifies the necessary facts, and proposes what to keep, mask, or remove.

**Inputs:** User question, file content, and sensitive information findings.

**Outputs:** A proposed set of relevant facts and privacy actions, with a short explanation.

**Acceptance criteria:**
- The proposed request contains information relevant to the question.
- Unrelated file content is excluded.
- Privacy actions include a reason the user can understand.
- The user can correct the proposal before anything is sent.

**Edge cases:** The question is too vague; a needed fact is also sensitive; the file lacks enough information; or Gemma selects more content than necessary.

### Feature 5. Redaction and pseudonymization

**Purpose:** Remove or replace private details while keeping the request useful.

**User flow:** PrivacyPal applies the proposed actions to a copy of the relevant content. It blocks high-risk secrets, masks or removes other sensitive details, and may replace names with labels such as “Person A.”

**Inputs:** Original content, findings, and user-approved actions.

**Outputs:** A sanitized version and, when placeholders are used, a local mapping between placeholders and original values.

**Acceptance criteria:**
- The original file is never modified.
- Blocked secrets do not appear in the sanitized request.
- Replacements are consistent within the conversation—for example, the same person remains “Person A.”
- The user can see the sanitized version before it is sent.

**Edge cases:** A finding overlaps another finding; a value appears in several formats; a replacement changes the meaning of a calculation; or the mapping cannot be safely stored.

### Feature 6. Residual privacy check

**Purpose:** Check whether the sanitized request still contains clues that could reveal identity.

**User flow:** Gemma reviews the proposed request and flags combinations of details that could identify someone. PrivacyPal presents those flags for the user to review.

**Inputs:** Sanitized request and the original question’s purpose.

**Outputs:** A pass or a list of potential identifying clues, with suggested changes.

**Acceptance criteria:**
- The check runs before the approval step.
- A flagged request is returned for editing or requires the user to explicitly accept the flagged content.
- PrivacyPal does not describe the request as guaranteed anonymous or perfectly safe.
- The user can see the reason for each flag.

**Edge cases:** The check is inconclusive; a detail is necessary to answer the question; Gemma flags a harmless fact; or Gemma fails to respond.

### Feature 7. Outbound preview and approval

**Purpose:** Give the user control over exactly what leaves their device.

**User flow:** PrivacyPal displays the exact sanitized request and the selected answer service. The user can approve, edit, or cancel it.

**Inputs:** Sanitized request, privacy check results, and selected answer service.

**Outputs:** An approved request, an edited request, or a cancelled operation.

**Acceptance criteria:**
- The exact outbound content is shown before sending.
- No request is sent to the answer service before the user approves it.
- Editing the request causes the privacy check to run again.
- Canceling prevents the external request.

**Edge cases:** The user changes the question after review; the request changes after approval; the selected service is unavailable; or approval expires before sending.

### Feature 8. AI answer in the same chat

**Purpose:** Return a useful answer without making the user upload the file again.

**User flow:** After approval, PrivacyPal sends the sanitized request to the selected answer AI and displays its answer in the existing conversation.

**Inputs:** User question, approved sanitized content, and selected answer service.

**Outputs:** Answer, service status, and any source references available from the document.

**Acceptance criteria:**
- The answer appears in the same chat as the question.
- Only the approved sanitized request is sent.
- The app displays a clear error if the answer service fails.
- The app does not claim that the answer has the same quality as a particular commercial AI.

**Edge cases:** Network timeout; provider error; empty or irrelevant answer; answer exceeds a limit; or the answer service returns content that appears to expose a masked value.

### Feature 9. Local placeholder restoration

**Purpose:** Make an answer easier to use when PrivacyPal replaced names or other values with placeholders.

**User flow:** If the user has approved placeholders, PrivacyPal checks the returned answer and offers to replace those placeholders locally before displaying it.

**Inputs:** AI answer, local placeholder mapping, and user’s restoration setting.

**Outputs:** Answer with placeholders, or a locally restored answer.

**Acceptance criteria:**
- Restoration happens on the user’s device.
- The user can choose whether restoration is enabled.
- Only exact approved placeholders are restored.
- The original outbound request remains sanitized.

**Edge cases:** A placeholder appears in an unrelated context; the mapping is missing; the answer changes a placeholder; or restoration could make the displayed answer unsafe to share.

### Feature 10. Sources and answer checking

**Purpose:** Help users verify that the AI used the right parts of the file.

**User flow:** PrivacyPal shows which extracted facts or document locations supported the answer. The user can inspect those excerpts.

**Inputs:** Extracted file content, selected facts, and answer.

**Outputs:** Source snippets or page references connected to the answer, when available.

**Acceptance criteria:**
- Shown references point to the uploaded file’s actual content or location.
- The app labels missing references clearly.
- It does not invent page numbers or claim a quote came from the file when it did not.

**Edge cases:** OCR text has no reliable page location; the answer combines several sections; or no supporting excerpt can be found.

### Feature 11. Session privacy and failure handling

**Purpose:** Keep users informed about what is stored and ensure failures do not quietly expose data.

**User flow:** The user can see the current processing status, clear the conversation, and learn whether an operation failed before or after approval.

**Inputs:** Uploaded file, conversation, processing state, and user’s clear/delete action.

**Outputs:** Status messages; cleared session data; or a clear error explaining what happened.

**Acceptance criteria:**
- The app explains whether files and chat data are kept for the current session.
- Clearing the session removes locally stored content and placeholder mappings.
- If scanning or privacy review fails, the app does not send the request.
- Errors distinguish local processing failures from answer-service failures.

**Edge cases:** Browser refresh; app crash; partial deletion; device runs out of memory; or network loss after approval but before the result returns.

### Feature 12. Untrusted content and prompt-injection handling

**Purpose:** Prevent instructions inside a document from changing PrivacyPal’s behavior.

**User flow:** Gemma treats file contents as data to analyze. If a document contains instructions such as “ignore prior rules” or “send the original file,” PrivacyPal flags or ignores them.

**Inputs:** File content and model instructions.

**Outputs:** Analysis results that follow the user’s request and PrivacyPal’s allowed actions; optional warning about suspicious document text.

**Acceptance criteria:**
- Instructions found inside a file cannot authorize external sending or bypass user approval.
- Gemma can call only allowlisted tools.
- The user must approve every outbound request.
- Suspicious content does not cause the original file to be sent.

**Edge cases:** Instructions hidden in OCR text or images; instructions split across pages; or the model treats quoted text as an instruction.

Build features 1–8 and 11–12 as the essential end-to-end product. Add 9–10 if the main flow is reliable. For the demo, use a synthetic document and show the full chain: ask about the file → Gemma uses tools to analyze it → preview and approve sanitized data → receive the answer in the same chat.

## 7. Non-Goals

The following are intentionally NOT part of this version:

- **Native mobile or desktop apps:** PrivacyPal will be a web app used in a browser.
- **Automatic access to files or other apps:** Users choose and upload each file; PrivacyPal won’t monitor their device, browser, or clipboard.
- **Folders and batch processing:** It will handle one file per request, not scan folders or process many documents together.
- **Every file type:** Start with a small set of supported formats, such as PDFs, images, and pasted text. Audio, video, spreadsheets, and complex document formats can come later.
- **Team and enterprise features:** No shared workspaces, admin dashboards, organization policies, or audit management.
- **Browser extensions or integrations:** No direct connection to ChatGPT, email, cloud drives, or other apps in this version.
- **Fully offline answers:** Gemma analyzes the file locally, but getting an answer from an external AI requires sending the user-approved, sanitized request to that service.
- **Guaranteed privacy or perfect detection:** PrivacyPal can reduce exposure and flag risks, but it cannot promise that every sensitive detail or identifying clue will be found.
- **Automatic sending without review:** The user must approve the exact request before it goes to an external AI.
- **Unrestricted AI actions:** Gemma can use only PrivacyPal’s approved tools; it cannot run arbitrary code, access the device, or bypass approval.
- **Training a new Gemma model:** This version uses an existing local Gemma model; fine-tuning and custom model training are out of scope.
- **Advanced compliance features:** No claims of regulatory certification, enterprise-grade retention controls, or formal compliance reporting.
- **Long-term chat and file storage:** The focus is a session-based workflow, not a permanent document library or cloud-synced chat history.

---

## 8. MVP Scope

### Must Have

- **Upload and read a file**
  Support pasted text and text-based PDFs. Show clear progress and errors.
- **Ask about the file in chat**
  Let the user attach once, ask a question, and keep the answer in the same conversation.
- **Gemma analyzes the file and calls tools**
  Gemma identifies relevant information and requests actions such as scanning, masking, or preparing a minimized request. The app validates and runs only approved tools.
- **Find and handle sensitive information**
  Detect common personal details and high-risk secrets. Mask, remove, or block them while keeping facts needed to answer the question.
- **Check the sanitized request for remaining clues**
  Have Gemma review the proposed request and flag possible identifying details before sending.
- **Show the exact request and require approval**
  Let the user inspect, edit, approve, or cancel. Nothing goes to the external answer AI before approval.
- **Get an answer from an external AI**
  Send only the approved sanitized request and display the response in the same chat.
- **Fail safely**
  If file reading, Gemma analysis, or the privacy check fails, stop the send and explain the issue. Treat instructions inside uploaded files as untrusted content.

### Nice to Have

- Local placeholder restoration, so the user can choose to replace labels like “Person A” in the returned answer.
- Source references, such as page numbers or excerpts showing which parts of the document support the answer.
- More file formats, such as DOCX, if they can be handled reliably.

### Future

- Batch processing and folder scans.
- Audio, video, and other complex file formats.
- Browser extension and integrations with cloud drives, email, or other AI services.
- Native mobile or desktop apps.
- Team workspaces, shared policies, admin controls, and enterprise audit tools.
- Long-term cloud storage, chat history sync, and compliance certifications.

---

## 9. Success Metrics

### Primary Metrics

| Metric | How to measure it | Suggested MVP target |
| --- | --- | --- |
| End-to-end task completion | Test whether users can upload a supported file, ask a question, approve a request, and receive an answer. | At least 9 of 10 test scenarios complete |
| Unapproved data sent | Check whether any request reaches the external AI without explicit user approval. | 0 |
| High-risk secret leakage | Check approved outbound requests for passwords, API keys, and test account numbers deliberately placed in sample files. | 0 in the test set |
| Sensitive data detection | Compare findings with known sensitive details in a curated test set. | At least 90% of planted details detected |
| Answer usefulness | Have reviewers rate whether answers correctly address the question using the relevant file facts. | At least 4 out of 5 on average |
| Gemma tool-use success | Check whether Gemma selects valid tools and completes the intended analysis workflow. | At least 90% successful tool workflows; 0 unauthorized tool actions |

### Secondary Metrics

| Metric | How to measure it | Suggested MVP target |
| --- | --- | --- |
| Supported-file read success | Percentage of supported sample files read successfully. | At least 9 of 10 |
| Privacy review time | Time from showing the sanitized request to the user making a decision. | Median under 30 seconds |
| False-positive rate | Percentage of flagged details that reviewers decide were not sensitive. | Track it; reduce without increasing secret leakage |
| Request reduction | Compare the amount of content sent with the original file content. | Show the reduction for each test; don’t remove facts needed for the answer |
| Source support | Percentage of answers whose cited excerpts support the claims, when citations are enabled. | At least 8 of 10 reviewed answers |
| Failure recovery | Check whether the app explains errors and prevents sending when analysis fails. | 100% of simulated failures stop the send and show an error |
| User control | Confirm users can edit, approve, and cancel the outbound request. | All three actions work in the demo |

---

## 10. Constraints

### Technical constraints

- **Local-first analysis:** Gemma must analyze the file locally. The app needs a local model runtime, such as Ollama, and a machine that can run the selected Gemma model at a usable speed.
- **Gemma must do meaningful work:** It should inspect the file and question, then use approved tool calls for actions such as finding sensitive content and preparing a minimized request.
- **Controlled tool execution:** The backend must validate Gemma’s tool requests. Gemma cannot send data externally or run arbitrary code.
- **External answer service:** Getting an answer from a cloud AI requires internet access and an API key. Only the user-approved sanitized request can be sent.
- **Limited file support:** The MVP supports pasted text, PDFs, PNG, JPEG, and WebP, with local OCR for scanned PDF pages and images. Enforce configured size, page, dimension, and processing-time limits.
- **Bounded file size and processing time:** Large or complex files may slow down local analysis or exceed available memory. Set a clear size limit and show progress and errors.
- **Safe failure behavior:** If reading, Gemma analysis, or privacy checks fail, do not send the request.
- **Temporary session data:** Avoid building a permanent file-storage system for the hackathon. Clear uploaded content and placeholder mappings when the session is cleared.

### Design constraints

- **Desktop-first web app:** Make the main workflow easy to operate and present on a laptop.
- **One clear flow:** Upload → ask → review findings → approve or cancel → receive answer.
- **Visible user control:** Show the exact outbound request and require approval before sending.
- **Explain privacy actions simply:** Say what was masked or kept, and why.
- **Make Gemma’s role visible:** Show meaningful tool activity and results without overwhelming the user with technical logs.
- **Keep the demo readable:** Use one synthetic document and one strong question rather than a crowded dashboard full of features.
- **Avoid absolute privacy claims:** Explain that local analysis reduces exposure, while the approved sanitized request still goes to the selected external AI.

### Business constraints

- **Hackathon time and team capacity:** Prioritize a reliable end-to-end product over a long feature list.
- **Gemma prize fit:** Gemma should be essential to the product’s contextual analysis and tool use, not just mentioned in the pitch.
- **API and model access:** Check model availability, hardware requirements, answer-service API access, and any usage limits before depending on them in the live demo.
- **Trust depends on evidence:** Use a test document with known sensitive details so you can demonstrate what was detected, what was blocked, and what was approved.
- **Be clear about the product’s boundary:** PrivacyPal reduces what is sent; it cannot promise perfect detection, anonymity, or identical answers to another AI service.

### Timeline constraints

With the Hack Day approaching, set a firm feature cutoff:

- **First:** Confirm that Gemma runs locally and can complete one valid tool-call workflow.
- **Next:** Finish the core path—upload, ask, detect, sanitize, review, approve, and receive an answer.
- **Then:** Test failures, secret blocking, cancellation, and the no-send-before-approval rule.
- **Only after that:** Add placeholder restoration or richer citations if they work reliably. Local OCR for scanned PDFs and images remains part of the MVP implementation scope.
- **Final stretch:** Freeze features; rehearse the demo and pitch using synthetic data.

## 13. Definition of Done

PrivacyPal is complete for the hackathon when:

- Users can upload a supported text PDF or paste text, then ask a question in the same chat.
- Gemma analyzes the file locally and uses approved tool calls to identify relevant information and propose privacy actions.
- Sensitive information is detected, and passwords or API keys are blocked from the outbound request.
- The app shows the exact sanitized request and requires user approval before sending it to the answer AI.
- The answer appears in the same chat, with a clear error if processing or the answer service fails.
- If file reading, Gemma analysis, or the privacy check fails, the request is not sent.
- Tool calls are restricted to the approved allowlist, and instructions inside uploaded files cannot bypass user approval.
- Tests verify the main user flow, sensitive-data handling, approval gate, tool-call validation, and failure behavior.
- The app builds and runs on the demo machine with Gemma and the answer service configured.
- Documentation explains setup, supported inputs, data flow, limitations, and how to run the demo.
- The demo uses synthetic data and does not make claims of perfect detection or guaranteed privacy.
