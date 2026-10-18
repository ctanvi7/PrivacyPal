import { useEffect, useId, useRef, useState } from 'react';
import { createDocumentUploadController } from './lib/documentUploadController.js';
import { createQuestionController } from './lib/questionController.js';
import { PRIVACY_ANALYSIS_TIMEOUT_MS, privacyPalApi } from './lib/privacyPalApi.js';
import ReviewTimeline from './components/ReviewTimeline.js';
import PrivacyChanges from './components/PrivacyChanges.js';
import { getWorkflowStatus, performWorkflowAction } from './lib/workflowActions.js';
import PrivacyReviewPanel from './components/PrivacyReviewPanel.jsx';
import { CLOUD_HOSTED, processingCopy } from './lib/deployment.js';


function Icon({ name, size = 20 }) {
  const props = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };
  const paths = {
    monitor: <><rect x="3.5" y="4.5" width="17" height="12" rx="1.8"/><path d="M8.5 20h7m-3.5-3.5V20"/></>, cube: <><path d="m12 2.8 8.5 4.7v9L12 21.2l-8.5-4.7v-9L12 2.8Z"/><path d="m3.8 7.7 8.2 4.6 8.2-4.6M12 12.3v8.5"/></>,
    eyeOff: <><path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A10.7 10.7 0 0 1 12 5c5.2 0 8.6 4.1 9.6 6.2a1.7 1.7 0 0 1 0 1.6 11.8 11.8 0 0 1-3.1 3.8M6.2 6.3A12.1 12.1 0 0 0 2.4 11.2a1.7 1.7 0 0 0 0 1.6C3.4 14.9 6.8 19 12 19c.9 0 1.8-.2 2.6-.4"/></>,
    plus: <path d="M12 5v14M5 12h14"/>, chat: <path d="M20 11.5a7.5 7.5 0 0 1-8 7.5 9 9 0 0 1-4-.9L4 20l1.2-3.4A7.1 7.1 0 0 1 4 12c0-4.1 3.6-7.5 8-7.5s8 2.9 8 7Z"/>,
    help: <><path d="M9.6 9a2.4 2.4 0 0 1 4.7.8c0 1.7-2.3 2-2.3 3.8"/><path d="M12 17h.01"/></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/></>, send: <><path d="m21 3-7.5 18-3.8-7.7L2 9.5 21 3Z"/><path d="m9.7 13.3 5-5"/></>,
    attach: <path d="m8 12.5 7.2-7.2a4 4 0 0 1 5.7 5.7l-9.8 9.8a6 6 0 0 1-8.5-8.5l9.2-9.2"/>, check: <path d="m5 12 4 4L19 6"/>, file: <><path d="M6 2.8h8l5 5V21H6z"/><path d="M14 3v5h5M9 13h7m-7 3h7"/></>,
    close: <path d="m6 6 12 12M18 6 6 18"/>, settings: <><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.1.9-1.2 2.1-1.4-.5a7.6 7.6 0 0 1-1.5.9l-.3 1.5h-2.4l-.3-1.5a7.6 7.6 0 0 1-1.5-.9l-1.4.5-1.2-2.1 1.1-.9a7.6 7.6 0 0 1 0-1.8l-1.1-.9 1.2-2.1 1.4.5a7.6 7.6 0 0 1 1.5-.9l.3-1.5h2.4l.3 1.5a7.6 7.6 0 0 1 1.5.9l1.4-.5 1.2 2.1-1.1.9a7.6 7.6 0 0 1-.1 1.7Z" transform="translate(-1 -1)"/></>,
    edit: <><path d="m15 5 4 4M4 20l4.3-.9L19 8.4a2.8 2.8 0 0 0-4-4L4.3 15.1 4 20Z"/></>,
  };
  return <svg {...props}>{paths[name] || paths.chat}</svg>;
}

function ShieldEmblem({ size = 30, className = '' }) {
  const gradientId = `shield-gradient-${useId().replaceAll(':', '')}`;
  const shineId = `shield-shine-${useId().replaceAll(':', '')}`;
  return <svg className={`shield-emblem ${className}`} width={size} height={size * 1.12} viewBox="0 0 48 54" fill="none" aria-hidden="true">
    <defs>
      <linearGradient id={gradientId} x1="7" y1="3" x2="40" y2="48" gradientUnits="userSpaceOnUse"><stop stopColor="#F5D8FF"/><stop offset=".22" stopColor="#D86BFF"/><stop offset=".58" stopColor="#9829E8"/><stop offset="1" stopColor="#541194"/></linearGradient>
      <linearGradient id={shineId} x1="10" y1="9" x2="23" y2="44" gradientUnits="userSpaceOnUse"><stop stopColor="#FFF4FF"/><stop offset=".42" stopColor="#F4BBFF"/><stop offset="1" stopColor="#A733ED"/></linearGradient>
    </defs>
    <path d="M24 2.1 43.4 9.2v14.1c0 12.1-7.8 22.3-19.4 28.7C12.4 45.6 4.6 35.4 4.6 23.3V9.2L24 2.1Z" fill={`url(#${gradientId})`} stroke="#F2C8FF" strokeWidth="1.3"/>
    <path d="M24 7.1 38.8 12.6v10.1c0 9.7-5.9 17.7-14.8 23.1-8.9-5.4-14.8-13.4-14.8-23.1V12.6L24 7.1Z" fill="#17101F" stroke="#5C2580" strokeWidth="1.1"/>
    <path d="M13.2 13.5 23.8 9.6v31.8c-6.5-4.9-10.6-11.4-10.6-19.1v-8.8Z" fill={`url(#${shineId})`} opacity=".96"/>
    <path d="M24 10.2 35 14.3v8.4c0 7.6-4.3 14.1-11 18.9V10.2Z" fill="#28143A" opacity=".92"/>
    <path d="m18.5 25.4 3.6 3.7 7.8-8.4" stroke="#F7E9FF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M8.1 10.9 22.7 5.5" stroke="#FFF0FF" strokeOpacity=".72" strokeWidth="1.1" strokeLinecap="round"/>
  </svg>;
}

function PrivacyPalLogo({ size = 40 }) {
  const gradientId = `privacypal-logo-gradient-${useId().replaceAll(':', '')}`;
  const highlightId = `privacypal-logo-highlight-${useId().replaceAll(':', '')}`;
  return <svg className="privacypal-logo" width={size} height={size * 1.16} viewBox="0 0 48 56" fill="none" role="img" aria-label="PrivacyPal shield logo">
    <defs>
      <linearGradient id={gradientId} x1="8" y1="5" x2="39" y2="48" gradientUnits="userSpaceOnUse"><stop stopColor="#F8DFFF"/><stop offset=".2" stopColor="#E77DFF"/><stop offset=".56" stopColor="#A329EE"/><stop offset="1" stopColor="#6819B8"/></linearGradient>
      <linearGradient id={highlightId} x1="8" y1="9" x2="19" y2="41" gradientUnits="userSpaceOnUse"><stop stopColor="#FFF1FF"/><stop offset=".55" stopColor="#D87BFF"/><stop offset="1" stopColor="#A43BE8" stopOpacity=".12"/></linearGradient>
    </defs>
    <path d="M24 2.8 43 9.4l-.7 15.4c-.6 11.8-7.4 21.5-18.3 28.4C13.1 46.3 6.3 36.6 5.7 24.8L5 9.4 24 2.8Z" fill={`url(#${gradientId})`} stroke="#F1C7FF" strokeWidth="1.25" strokeLinejoin="round"/>
    <path d="M24 7.1 38.5 12l-.6 12.5c-.5 9.7-5.7 17.7-13.9 23.5-8.2-5.8-13.4-13.8-13.9-23.5L9.5 12 24 7.1Z" fill="#100D16" stroke="#552078" strokeWidth="1.05" strokeLinejoin="round"/>
    <path d="m7.2 10.5 15.5-5.4" stroke={`url(#${highlightId})`} strokeWidth="2.1" strokeLinecap="round"/>
    <path d="M8.1 11.3 9 24.4c.5 10.1 5.1 18.6 13.4 24.8" stroke={`url(#${highlightId})`} strokeWidth="1.35" strokeLinecap="round" opacity=".88"/>
  </svg>;
}

function ShieldMark({ className = '', size = 26 }) { return <span className={`shield-mark ${className}`}><ShieldEmblem size={size}/></span>; }

function FileChip({ file, uploadResult, uploaded = false, onRemove, disabled = false }) {
  const size = `${Math.max(1, Math.round(file.size / 1024))} KB${uploadResult?.page_count ? ` / ${uploadResult.page_count} ${uploadResult.page_count === 1 ? 'page' : 'pages'}` : ''}`;
  return <div className="file-chip"><span className="file-icon">{file.name.split(".").pop()?.slice(0, 4).toUpperCase() || "FILE"}</span><span className="file-name"><strong title={file.name}>{file.name}</strong><small>{size} - {uploaded ? processingCopy('processed locally') : 'selected in this browser'}</small></span><button type="button" className="icon-button" aria-label="Remove selected document" onClick={onRemove} disabled={disabled}><Icon name="close" size={18}/></button></div>;
}

function EmptyConversation({ onChoose }) {
  return <div className="empty-state"><div className="empty-shield"><ShieldEmblem size={36}/></div><h2>What would you like to understand?</h2><p>Choose a document, then ask a question. Youâ€™ll review what may be shared before anything is sent to an AI provider.</p><button className="upload-cta" type="button" onClick={onChoose}><Icon name="attach" size={19}/>Choose a document</button><span className="supported">PDF, PNG, JPEG, or WebP{CLOUD_HOSTED ? ' - up to 4 MiB' : ''}</span><div className="empty-reassurance"><ShieldMark/><p>{CLOUD_HOSTED ? 'Documents are uploaded to your AWS environment for processing. Review the exact request before anything is sent to the answer provider.' : 'Your original document stays on this device. Any approved request sent to an external provider will be shown for review first.'}</p></div></div>;
}

function App() {
  const fileInput = useRef(null);
  const [uploadController] = useState(() => createDocumentUploadController({
    createSession: options => privacyPalApi.createSession(options),
    uploadDocument: (sessionId, selectedFile, options) => privacyPalApi.uploadDocument(sessionId, selectedFile, options),
  }));
  const [uploadState, setUploadState] = useState(uploadController.getState);
  const [questionController] = useState(() => createQuestionController({ timeoutMs: PRIVACY_ANALYSIS_TIMEOUT_MS + 5_000,
    submitQuestion: (text, document, { signal, session }) => privacyPalApi.submitQuestion(session.session_id, document.document_id, text, { signal }),
  }));
  const [questionState, setQuestionState] = useState(questionController.getState);
  const [activeWorkflow, setActiveWorkflow] = useState(null);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [workflowError, setWorkflowError] = useState('');
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [question, setQuestion] = useState('');
  const [notice, setNoticeState] = useState('');
  const setNotice = message => setNoticeState(processingCopy(message));
  const file = uploadState.selectedFile;

  useEffect(() => uploadController.subscribe(setUploadState), [uploadController]);
  useEffect(() => questionController.subscribe(setQuestionState), [questionController]);
  useEffect(() => { if (questionState.result) setActiveWorkflow(questionState.result); }, [questionState.result]);

  async function startNewChat() {
    if (cleanupBusy || uploadState.status === 'uploading' || questionState.status === 'processing' || workflowBusy) return;
    setCleanupBusy(true);
    try {
      const sessionId = uploadState.session?.session_id;
      if (sessionId) await privacyPalApi.clearSession(sessionId);
      uploadController.reset(); questionController.reset(); setActiveWorkflow(null); setWorkflowError(''); setQuestion(''); setNotice('');
      if (fileInput.current) fileInput.current.value = '';
    } catch (error) {
      setNotice(`Could not clear the local session. Your current document and session are still shown. ${error?.message || ''}`.trim());
    } finally { setCleanupBusy(false); }
  }

  async function selectDocument(candidate) {
    if (!candidate) return;
    const selected = uploadController.select(candidate);
    if (selected.error?.code === 'unsupported_file') { setNotice(selected.error.message); if (fileInput.current) fileInput.current.value = ''; return; }
    questionController.reset(); setActiveWorkflow(null); setWorkflowError(''); setQuestion('');
    setNotice('Creating a private session and uploading your document...');
    const confirmed = await uploadController.upload();
    if (uploadController.getState().selectedFile !== candidate) return;
    const result = uploadController.getState();
    setNotice(confirmed ? 'Document uploaded and confirmed by the local service. Ask a question to start local privacy analysis.' : result.error?.message || 'The document was not confirmed by the local service.');
  }

  async function removeDocument() {
    if (cleanupBusy || uploadState.status === 'uploading' || questionState.status === 'processing' || workflowBusy) return;
    setCleanupBusy(true);
    try {
      const sessionId = uploadState.session?.session_id;
      const documentId = uploadState.uploadedDocument?.document_id;
      if (sessionId && documentId) await privacyPalApi.removeDocument(sessionId, documentId);
      else if (sessionId) await privacyPalApi.clearSession(sessionId);
      uploadController.forgetDocument(); questionController.reset(); setActiveWorkflow(null); setWorkflowError(''); setQuestion('');
      setNotice('Document removed from the local session.'); if (fileInput.current) fileInput.current.value = '';
    } catch (error) {
      setNotice(`The local service did not confirm document removal, so the document and session remain shown. ${error?.message || ''}`.trim());
    } finally { setCleanupBusy(false); }
  }

  async function submitQuestion(event) {
    event.preventDefault(); setNotice(''); setWorkflowError(''); setActiveWorkflow(null);
    await questionController.submit({ question, uploadedDocument: uploadState.uploadedDocument, session: uploadState.session, uploadedSessionId: uploadState.uploadedSessionId });
    const submission = questionController.getState();
    if (submission.error) setNotice(submission.error.message);
    else if (submission.status === 'review-ready') setNotice('Local privacy analysis returned. Review the exact request below; nothing has been sent to an answer provider.');
  }

  async function retryQuestion() {
    setNotice('');
    await questionController.retry({ uploadedDocument: uploadState.uploadedDocument, session: uploadState.session, uploadedSessionId: uploadState.uploadedSessionId });
    const submission = questionController.getState(); setNotice(submission.error?.message || 'Question processing completed.');
  }

  function runWorkflowAction(action, approval = false) {
    return performWorkflowAction({
      workflow: activeWorkflow, sessionId: uploadState.session?.session_id,
      busy: workflowBusy, action, approval,
      setWorkflow: setActiveWorkflow, setBusy: setWorkflowBusy, setError: setWorkflowError,
    });
  }
  function saveDraft(draft) {
    return runWorkflowAction((sid, workflowId, version) => privacyPalApi.editWorkflowDraft(sid, workflowId, version, draft));
  }
  function acknowledgeWarnings() {
    return runWorkflowAction((sid, workflowId, version) => privacyPalApi.acknowledgeWorkflow(sid, workflowId, version));
  }
  async function cancelReview() {
    const result = await runWorkflowAction(async (sid, workflowId) => {
      await privacyPalApi.cancelWorkflow(sid, workflowId);
      return { ...activeWorkflow, send_state: 'cancelled' };
    });
    if (result) setNotice('Review cancelled. No answer request was sent.');
  }
  async function approveWorkflow() {
    setNotice('');
    await runWorkflowAction((sid, workflowId, version) => privacyPalApi.approveWorkflow(sid, workflowId, version), true);
  }

  const workflowStatus = activeWorkflow ? getWorkflowStatus(activeWorkflow) : null;
  const questionFailed = questionState.status === 'processing-error';
  const findings = activeWorkflow?.findings || [];
  const pagesUsed = activeWorkflow?.pages_used || [];
  const localAnalysisStatus = uploadState.status === 'uploaded' ? 'Document ready' : uploadState.status === 'uploading' ? 'Processing locally' : 'Ready for a document';

  return <main className="workspace" data-upload-state={uploadState.status} data-question-state={questionState.status}>
    <aside className="sidebar glass-panel" aria-label="Conversation navigation">
      <a className="brand" href="#home" onClick={event => { event.preventDefault(); startNewChat(); }} aria-label="PrivacyPal home"><span className="brand-mark"><PrivacyPalLogo size={40}/></span><span><strong>PrivacyPal</strong><small>{CLOUD_HOSTED ? 'Your private AWS workspace.' : 'Your data stays with you.'}</small></span></a>
      <button className="new-chat" type="button" onClick={startNewChat} disabled={cleanupBusy || uploadState.status === 'uploading' || questionState.status === 'processing' || workflowBusy}><span className="plus-disc"><Icon name="plus" size={20}/></span><b>New chat</b><kbd>Ctrl N</kbd></button>
      <nav className="recent-list" aria-label="Conversation history"><p className="nav-label">Today</p>{question ? <p className="recent current-session"><Icon name="chat" size={18}/><span>{question.slice(0, 38)}{question.length > 38 ? '...' : ''}</span></p> : <p className="recent-empty">No conversation yet</p>}<p className="nav-label previous-label">Previous 7 days</p><p className="recent-empty">No saved conversations</p></nav>
      <div className="local-status"><span className="gemma-icon" aria-hidden="true"><Icon name="cube" size={35}/></span><div><strong>{processingCopy('Local analysis')}</strong><p>{localAnalysisStatus}. Documents stay in in-memory session state.</p></div><span className="status-orb" aria-label={localAnalysisStatus}/></div>
      <div className="side-links"><button type="button" onClick={() => setNotice('Settings are not available in this frontend yet.')}><Icon name="settings" size={18}/>Settings</button><button type="button" onClick={() => setNotice('Help and feedback are not connected yet.')}><span className="help-icon"><Icon name="help" size={14}/></span>Help &amp; feedback</button></div>
    </aside>

    <section className="chat-column" aria-label="Private chat">
      <header className="chat-header"><div><div className="title-row"><h1>Private chat</h1><span className="local-badge"><Icon name="monitor" size={18}/> {processingCopy('Local analysis')}</span></div><p>{CLOUD_HOSTED ? 'Documents are processed in AWS. You control what goes to the answer provider.' : 'Get helpful answers from AI, with your privacy in control.'}</p><span className="connection-label">{uploadState.status === 'uploaded' ? processingCopy('Local service - document ready') : processingCopy('Local privacy review before any provider request')}</span></div><button className="mobile-privacy" type="button" onClick={() => document.getElementById('privacy-panel')?.scrollIntoView({ behavior: 'smooth' })}>Privacy details</button></header>

      <div className="conversation" role="region" aria-label="Chat messages" aria-live="polite" tabIndex={0}>
        {file ? <>
          <div className="user-row"><div className="user-message"><p>{question || (uploadState.status === 'uploaded' ? 'Document ready for a question' : uploadState.status === 'uploading' ? 'Uploading document' : 'Document selected')}</p><FileChip file={file} uploadResult={uploadState.uploadedDocument} uploaded={uploadState.status === 'uploaded'} onRemove={removeDocument} disabled={cleanupBusy || uploadState.status === 'uploading' || questionState.status === 'processing' || workflowBusy}/></div><span className="user-avatar" aria-hidden="true"><span/></span></div>
          {activeWorkflow ? <><div className="assistant-row"><ShieldMark className="assistant-avatar"/><div className="assistant-message"><p>{activeWorkflow.review_complete ? processingCopy('Local review complete.') : activeWorkflow.residual_review?.status === 'blocked' ? processingCopy('Local review needs attention.') : processingCopy('Local review is incomplete.')}</p><p>{activeWorkflow.send_state === 'review' ? 'Review the exact request before deciding whether to get an answer.' : workflowStatus.detail}</p></div></div><PrivacyReviewPanel response={activeWorkflow} busy={workflowBusy} error={workflowError} onEdit={saveDraft} onAcknowledge={acknowledgeWarnings} onApprove={approveWorkflow} onCancel={cancelReview}/></> : <div className="pending-card glass-panel"><span className="pending-icon"><Icon name="lock" size={22}/></span><div><h2>{questionFailed ? 'Privacy review needs attention' : uploadState.status === 'uploading' ? processingCopy('Reading document locally') : uploadState.status === 'upload-error' || uploadState.status === 'cancelled' ? 'Upload needs attention' : questionState.status === 'processing' ? processingCopy('Checking your question locally') : 'Ready for your question'}</h2><p>{questionFailed ? 'The review stopped before a draft was ready. Check the failed step and retry below.' : uploadState.status === 'uploading' ? processingCopy('The local service is processing the selected file.') : uploadState.status === 'uploaded' ? processingCopy('Ask a question to run the local privacy review. Nothing is sent to an answer provider at this stage.') : uploadState.error?.message || 'The selected file remains local until the service confirms a successful upload.'}</p>{uploadState.status === 'uploading' && <button className="edit-button" type="button" onClick={() => uploadController.cancel()}>Cancel upload</button>}{uploadState.error?.retryable && <button className="edit-button" type="button" onClick={() => uploadController.retry()}>Retry upload</button>}</div></div>}
        </> : <EmptyConversation onChoose={() => fileInput.current?.click()}/>}
        {questionState.status === 'processing' && <div className="notice" role="status">{processingCopy('Local privacy analysis is in progress.')} <button type="button" onClick={() => { questionController.cancel(); setNotice('Question submission cancelled.'); }}>Cancel</button></div>}
        {questionState.status === 'processing-error' && questionState.error?.retryable && uploadState.uploadedDocument && <div className="notice" role="status">{questionState.error.message} <button type="button" onClick={retryQuestion}>Retry question</button></div>}
        {notice && !(questionFailed && notice === questionState.error?.message && questionState.error?.retryable) && <p className="notice" role="status">{notice}</p>}
      </div>

      <form className="composer glass-panel" onSubmit={submitQuestion}><input ref={fileInput} className="visually-hidden" type="file" accept="application/pdf,image/png,image/jpeg,image/webp" aria-label="Choose a document" onChange={event => selectDocument(event.target.files?.[0])}/><button className="attach-button" type="button" aria-label="Attach a document" onClick={() => fileInput.current?.click()} disabled={uploadState.status === 'uploading' || questionState.status === 'processing'}><Icon name="attach" size={20}/></button><label className="visually-hidden" htmlFor="question">Ask a question about your document</label><textarea id="question" value={question} onChange={event => { setQuestion(event.target.value); questionController.setQuestion(event.target.value); if (notice) setNotice(''); }} placeholder={file ? 'Ask a question about this document?' : 'Choose a document to start a private chat...'} rows="1" disabled={!file || uploadState.status !== 'uploaded' || questionState.status === 'processing'}/><button className="send-button" type="submit" aria-label="Submit question" disabled={!file || uploadState.status !== 'uploaded' || questionState.status === 'processing' || !question.trim()}><Icon name="send" size={19}/></button></form>
    </section>

    <aside id="privacy-panel" className="privacy-panel glass-panel" aria-label="Privacy review status">
      <div className="privacy-heading"><span className="privacy-icon"><PrivacyPalLogo size={34}/></span><div><h2>Privacy check</h2><p>{activeWorkflow ? processingCopy('Findings and progress from the local review.') : uploadState.status === 'uploaded' ? processingCopy('Local analysis starts after you ask a question.') : 'Analysis details appear after a document is loaded.'}</p></div></div>
      <div className="summary-grid">
        <div className="summary-card">
          <span className="summary-symbol warning"><Icon name="eyeOff" size={19}/></span>
          <div><strong>{activeWorkflow ? findings.length : questionFailed ? 'Review incomplete' : 'No findings yet'}</strong><p>Findings</p></div>
          <small>{activeWorkflow ? processingCopy('Returned by local checks') : questionFailed ? 'The review stopped before results were ready' : uploadState.status === 'uploaded' ? processingCopy('Ask a question to run local checks') : processingCopy('Local findings will appear here')}</small>
        </div>
        <div className="summary-card">
          <span className="summary-symbol violet"><Icon name="file" size={18}/></span>
          <div><strong>{activeWorkflow ? pagesUsed.length : questionFailed ? 'Not completed' : 'No document analyzed'}</strong><p>{activeWorkflow ? 'Pages used' : 'Document analysis'}</p></div>
          <small>{activeWorkflow ? processingCopy('Source pages returned by local review') : questionFailed ? 'Retry the privacy review' : uploadState.status === 'uploaded' ? 'Upload is ready; analysis has not run' : 'Upload a document to begin'}</small>
        </div>
      </div>
      <ReviewTimeline uploadStatus={uploadState.status} uploadResult={uploadState.uploadedDocument} uploadError={uploadState.error} questionStatus={questionState.status} questionError={questionState.error} workflowResponse={activeWorkflow}/>
      {activeWorkflow && <PrivacyChanges response={activeWorkflow}/>}
      <div className="control-note"><span className="note-lock"><Icon name="lock" size={24}/></span><div><strong>You are in control</strong><p>{activeWorkflow && activeWorkflow.send_state !== 'review' ? workflowStatus.detail : activeWorkflow ? 'Nothing is sent until you approve the exact text on the left.' : 'Nothing is sent to an answer provider before an explicit approval.'}</p></div></div>
    </aside>
  </main>;
}
export default App;
