import { useRef, useState } from "react";

const API = "http://127.0.0.1:8000";

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API}${path}`, options);
  } catch {
    throw new Error("Could not reach PrivacyPal's local service. Check that the backend is running.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error?.message || body.detail || "The request could not be completed.");
  return body;
}

export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [file, setFile] = useState(null);
  const [pastedText, setPastedText] = useState("");
  const [document, setDocument] = useState(null);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef(null);

  async function getSession() {
    if (sessionId) return sessionId;
    const result = await request("/api/v1/sessions", { method: "POST" });
    setSessionId(result.session_id);
    return result.session_id;
  }

  async function attachDocument(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const id = await getSession();
      const options = pastedText.trim()
        ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pasted_text: pastedText }) }
        : (() => {
            const form = new FormData();
            form.append("file", file);
            return { method: "POST", body: form };
          })();
      setDocument(await request(`/api/v1/sessions/${id}/documents`, options));
      setMessages([]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function ask(event) {
    event.preventDefault();
    if (!document || !question.trim()) return;
    const asked = question.trim();
    setQuestion("");
    setMessages((current) => [...current, { role: "user", text: asked }]);
    setBusy(true);
    setError("");
    try {
      const result = await request(`/api/v1/sessions/${sessionId}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: document.document_id, question: asked }),
      });
      setMessages((current) => [...current, { role: "assistant", text: result.answer, pages: result.pages_used }]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function clearSession() {
    setBusy(true);
    try {
      if (sessionId) await request(`/api/v1/sessions/${sessionId}/clear`, { method: "POST" });
    } catch {
      // Clearing this browser state remains useful if the local service stopped.
    }
    setSessionId(null);
    setFile(null);
    setPastedText("");
    setDocument(null);
    setQuestion("");
    setMessages([]);
    setError("");
    if (fileInput.current) fileInput.current.value = "";
    setBusy(false);
  }

  async function removeDocument() {
    setBusy(true);
    try {
      if (sessionId) await request(`/api/v1/sessions/${sessionId}/documents/${document.document_id}`, { method: "DELETE" });
    } catch (err) {
      setError(err.message);
      setBusy(false);
      return;
    }
    setDocument(null);
    setMessages([]);
    setBusy(false);
  }

  const canAttach = Boolean(file || pastedText.trim());

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Workspace information">
        <div className="brand"><span className="brand-mark" aria-hidden="true">P</span><span>PrivacyPal</span></div>
        <div className="local-card">
          <span className="status-dot" />
          <div><strong>Local analysis</strong><small>Gemma runs through Ollama on this computer.</small></div>
        </div>
        <div className="sidebar-note"><span className="eyebrow">YOUR WORKSPACE</span><p>Documents and questions stay in temporary session memory.</p></div>
        <button className="quiet-button clear-button" onClick={clearSession} disabled={busy}>Clear session</button>
      </aside>

      <section className="chat-panel" aria-label="Document chat">
        <header className="topbar"><div><span className="eyebrow">PRIVATE DOCUMENT WORKSPACE</span><h1>Ask about a document</h1></div><span className="model-pill">Gemma · local</span></header>

        <div className="conversation" aria-live="polite">
          {messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon" aria-hidden="true">✳</div>
              <h2>Start with a document</h2>
              <p>Add a document or paste text, then ask Gemma a question. The first version supports PDF, PNG, JPEG, WebP, and pasted text.</p>
              <div className="steps"><span><b>01</b> Add a document</span><span><b>02</b> Ask a question</span><span><b>03</b> Get a local analysis</span></div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map((message, index) => (
                <article className={`message ${message.role}`} key={`${index}-${message.role}`}>
                  <span className="message-label">{message.role === "user" ? "YOU" : "GEMMA · LOCAL"}</span>
                  <p>{message.text}</p>
                  {message.pages?.length > 0 && <small className="page-reference">Source pages: {message.pages.join(", ")}</small>}
                </article>
              ))}
              {busy && document && <div className="activity"><span className="spinner" /> Gemma is checking relevant passages locally…</div>}
            </div>
          )}
          {error && <div className="error-banner" role="alert">{error}</div>}
        </div>

        <div className="composer-area">
          {document ? (
            <div className="attached-document"><span className="file-icon" aria-hidden="true">▤</span><div><strong>Document ready</strong><small>{document.page_count} {document.page_count === 1 ? "page" : "pages"} · {document.character_count.toLocaleString()} characters · processed locally</small></div><button className="remove-button" onClick={removeDocument} aria-label="Remove document" disabled={busy}>×</button></div>
          ) : (
            <form className="attach-card" onSubmit={attachDocument}>
              <div className="attach-heading"><div><span className="eyebrow">ADD SOURCE</span><h2>Choose a file or paste text</h2></div><span className="file-types">PDF · PNG · JPG · WEBP</span></div>
              <textarea aria-label="Paste document text" placeholder="Paste text here…" value={pastedText} onChange={(event) => { setPastedText(event.target.value); if (event.target.value) { setFile(null); if (fileInput.current) fileInput.current.value = ""; } }} maxLength={25000} />
              <div className="attach-actions"><label className="quiet-button file-picker">{file ? file.name : "Choose file"}<input ref={fileInput} type="file" accept="application/pdf,image/png,image/jpeg,image/webp" onChange={(event) => { setFile(event.target.files?.[0] || null); setPastedText(""); }} /></label><span className="limit-label">Up to 10 MiB · 25 pages</span><button className="primary-button" type="submit" disabled={!canAttach || busy}>{busy ? "Reading locally…" : "Add document"}</button></div>
              <p className="privacy-note">Files are processed on this computer. Unsupported, unreadable, or oversized files are stopped.</p>
            </form>
          )}

          <form className="question-form" onSubmit={ask}>
            <label className="sr-only" htmlFor="question">Ask a question about the document</label>
            <textarea id="question" placeholder={document ? "Ask a question about your document…" : "Add a document to start asking…"} value={question} onChange={(event) => setQuestion(event.target.value)} disabled={!document || busy} maxLength={2000} rows={2} />
            <div className="question-bottom"><span>{document ? "Your question and relevant passages are analyzed locally." : "Your document is needed before you can ask."}</span><button className="send-button" aria-label="Send question" disabled={!document || !question.trim() || busy}>↑</button></div>
          </form>
          <p className="disclosure">Document processing and Gemma analysis run locally through Ollama.</p>
        </div>
      </section>
    </main>
  );
}
