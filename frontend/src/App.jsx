import { useEffect, useId, useReducer, useRef, useState } from 'react';
import { createDocumentUploadController } from './lib/documentUploadController.js';
import { createQuestionController } from './lib/questionController.js';
import { createPrivacyReviewController } from './lib/privacyReview.js';
import { createInitialWorkflowState, workflowReducer } from './lib/workflow.js';
import PrivacyReviewPanel from './components/PrivacyReviewPanel.jsx';

const SAMPLE_REQUEST = 'Monthly take-home pay: ?72,000\nPlanned rent: ?28,000 per month\nQuestion: Is this rent affordable as a share of monthly income?';

function Icon({ name, size = 20 }) {
  const props = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };
  const paths = {
    monitor: <><rect x="3.5" y="4.5" width="17" height="12" rx="1.8"/><path d="M8.5 20h7m-3.5-3.5V20"/></>, cube: <><path d="m12 2.8 8.5 4.7v9L12 21.2l-8.5-4.7v-9L12 2.8Z"/><path d="m3.8 7.7 8.2 4.6 8.2-4.6M12 12.3v8.5"/></>,
    eyeOff: <><path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A10.7 10.7 0 0 1 12 5c5.2 0 8.6 4.1 9.6 6.2a1.7 1.7 0 0 1 0 1.6 11.8 11.8 0 0 1-3.1 3.8M6.2 6.3A12.1 12.1 0 0 0 2.4 11.2a1.7 1.7 0 0 0 0 1.6C3.4 14.9 6.8 19 12 19c.9 0 1.8-.2 2.6-.4"/></>,
    plus: <path d="M12 5v14M5 12h14"/>, chat: <path d="M20 11.5a7.5 7.5 0 0 1-8 7.5 9 9 0 0 1-4-.9L4 20l1.2-3.4A7.1 7.1 0 0 1 4 12c0-4.1 3.6-7.5 8-7.5s8 2.9 8 7Z"/>,
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

function FileChip({ file, sample = false, onRemove }) {
  const name = sample ? 'October payslip.pdf' : file.name;
  const size = sample ? '195 KB ? sample document' : `${Math.max(1, Math.round(file.size / 1024))} KB ? selected in this browser`;
  return <div className="file-chip"><span className="file-icon">PDF</span><span className="file-name"><strong title={name}>{name}</strong><small>{size}</small></span>{sample ? <span className="sample-x" aria-hidden="true"><Icon name="close" size={18}/></span> : <button type="button" className="icon-button" aria-label="Remove selected document" onClick={onRemove}><Icon name="close" size={18}/></button>}</div>;
}

function ReviewTimeline({ mode }) {
  const sample = mode === 'preview';
  const documentSelected = mode === 'document';
  const steps = sample ? [
    ['Read PDF', 'Example ? extracted text from 1 page'], ['Find sensitive details', 'Example ? 3 details identified'], ['Keep answer facts', 'Example ? 2 relevant facts selected'], ['Check remaining clues', 'Example ? review not performed'],
  ] : [
    ['Read PDF', documentSelected ? 'Waiting for local backend' : 'Select a document to begin'], ['Find sensitive details', 'Not started'], ['Keep answer facts', 'Not started'], ['Check remaining clues', 'Not started'],
  ];
  return <div className={`review-steps ${sample ? 'is-sample' : ''}`} aria-label={sample ? 'Illustrative review steps' : 'Privacy review steps'}>{steps.map(([title, detail], i) => <div className="timeline-item" key={title}><span className={`step-number ${sample ? '' : 'incomplete'}`}>{sample ? <Icon name="check" size={16}/> : i + 1}</span><div><strong>{title}</strong>{sample && <time>10:24 AM</time>}<p>{detail}</p></div></div>)}</div>;
}

function EmptyConversation({ onChoose }) {
  return <div className="empty-state"><div className="empty-shield"><ShieldEmblem size={36}/></div><h2>What would you like to understand?</h2><p>Choose a document, then ask a question. You?ll review what may be shared before anything is sent to an AI provider.</p><button className="upload-cta" type="button" onClick={onChoose}><Icon name="attach" size={19}/>Choose a document</button><span className="supported">PDF, PNG, JPEG, or WebP</span><div className="empty-reassurance"><ShieldMark/><p>Your original document stays on this device. Any approved request sent to an external provider will be shown for review first.</p></div></div>;
}

function App() {
  const fileInput = useRef(null);
  const [uploadController] = useState(() => createDocumentUploadController());
  const [uploadState, setUploadState] = useState(uploadController.getState);
  const [questionController] = useState(() => createQuestionController());
  const [questionState, setQuestionState] = useState(questionController.getState);
  const [reviewController] = useState(() => createPrivacyReviewController());
  const [reviewState, setReviewState] = useState(reviewController.getState);
  const [workflow, dispatchWorkflow] = useReducer(workflowReducer, undefined, createInitialWorkflowState);
  const [mode, setMode] = useState('empty');
  const [question, setQuestion] = useState('');
  const [draft, setDraft] = useState(SAMPLE_REQUEST);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState('');
  const file = uploadState.selectedFile;

  useEffect(() => uploadController.subscribe(setUploadState), [uploadController]);
  useEffect(() => questionController.subscribe(setQuestionState), [questionController]);
  useEffect(() => reviewController.subscribe(setReviewState), [reviewController]);

  useEffect(() => {
    function handleShortcut(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault();
        startNewChat();
      }
    }
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, []);

  function openPreview() { uploadController.reset(); questionController.reset(); reviewController.reset(); dispatchWorkflow({ type: 'RESET' }); setMode('preview'); setQuestion(''); setEditing(false); setDraft(SAMPLE_REQUEST); setNotice('This conversation contains illustrative sample data only.'); if (fileInput.current) fileInput.current.value = ''; }

  function startNewChat() {
    uploadController.reset();
    questionController.reset();
    reviewController.reset();
    dispatchWorkflow({ type: 'RESET' });
    setMode('empty');
    setDraft(SAMPLE_REQUEST);
    setEditing(false);
    setQuestion('');
    setNotice('');
    if (fileInput.current) fileInput.current.value = '';
  }

  function selectDocument(candidate) {
    if (!candidate) return;
    const selected = uploadController.select(candidate);
    if (selected.error?.code === 'unsupported_file') {
      setNotice(selected.error.message);
      if (fileInput.current) fileInput.current.value = '';
      return;
    }
    dispatchWorkflow({ type: 'DOCUMENT_SELECTED', document: candidate });
    questionController.reset();
    reviewController.reset();
    setQuestion('');
    setMode('document');
    setEditing(false);
    setNotice('File selected in this browser. Backend connection is pending; the file has not been uploaded or analyzed.');
  }

  function removeDocument() {
    uploadController.reset();
    questionController.reset();
    reviewController.reset();
    dispatchWorkflow({ type: 'RESET' });
    setQuestion('');
    setMode('empty');
    setNotice('Document removed.');
    if (fileInput.current) fileInput.current.value = '';
  }

  async function submitQuestion(event) {
    event.preventDefault();
    if (mode === 'preview') { setNotice('This is a demo conversation. Questions and requests in the preview are not sent.'); return; }
    await questionController.submit({ question, uploadedDocument: uploadState.uploadedDocument });
    const submission = questionController.getState();
    if (submission.error) setNotice(submission.error.message);
    else if (submission.status === 'review-ready') setNotice('A response was received; connect an explicit backend review adapter before displaying it as a privacy review.');
  }

  async function retryQuestion() {
    await questionController.retry({ uploadedDocument: uploadState.uploadedDocument });
    const submission = questionController.getState();
    setNotice(submission.error?.message || 'Question processing completed.');
  }

  const hasPreview = mode === 'preview';

  return <main className="workspace" data-workflow-state={workflow.status} data-upload-state={uploadState.status} data-question-state={questionState.status}>
    <aside className="sidebar glass-panel" aria-label="Conversation navigation">
      <a className="brand" href="#home" onClick={event => { event.preventDefault(); startNewChat(); }} aria-label="PrivacyPal home"><span className="brand-mark"><PrivacyPalLogo size={40}/></span><span><strong>PrivacyPal</strong><small>Privacy in your control.</small></span></a>
      <button className="new-chat" type="button" onClick={startNewChat}><span className="plus-disc"><Icon name="plus" size={20}/></span><b>New chat</b><kbd>? N</kbd></button>
      <nav className="recent-list" aria-label="Recent chats"><p className="nav-label">Today ? sample history</p><button className={`recent ${hasPreview ? 'active' : ''}`} type="button" onClick={openPreview}><Icon name="chat" size={18}/><span>Rent affordability <small className="recent-sample">Illustrative preview</small></span><time>10:24 AM</time></button><p className="nav-label previous-label">Previous 7 days ? examples</p>{['Home loan options','Tax saving ideas','Compare mutual funds'].map((item, i) => <button className="recent" type="button" key={item} onClick={() => setNotice('This conversation is not stored in this frontend yet.')}><Icon name="chat" size={17}/><span>{item}</span><time>Oct {28-i*2}</time></button>)}</nav>
      <div className="local-status"><span className="gemma-icon" aria-hidden="true"><Icon name="cube" size={35}/></span><div><strong>Local model ? pending</strong><p>Backend API is not implemented.<br/>No document has been analyzed.</p></div><span className="status-orb" aria-label="Connection pending"/></div>
      <div className="side-links"><button type="button" onClick={() => setNotice('Settings are not available in this frontend yet.')}><Icon name="settings" size={18}/>Settings</button><button type="button" onClick={() => setNotice('Help and feedback are not connected yet.')}><span className="help-icon">?</span>Help &amp; feedback</button></div>
    </aside>

    <section className="chat-column" aria-label="Private chat">
      <header className="chat-header"><div><div className="title-row"><h1>Private chat</h1><span className="local-badge"><Icon name="monitor" size={18}/>Local analysis</span></div><p>Get helpful answers from AI, with your privacy in control.</p><span className={`connection-label ${hasPreview ? 'sample' : ''}`}>{hasPreview ? 'Illustrative preview ? demo data only' : 'Backend connection pending ? no analysis has run'}</span></div><button className="mobile-privacy" type="button" onClick={() => document.getElementById('privacy-panel')?.scrollIntoView({ behavior: 'smooth' })}>Privacy details</button></header>

      <div className={`conversation ${hasPreview ? 'sample-conversation' : 'empty-conversation'}`} aria-live="polite">
        {hasPreview ? <>
          <div className="user-row"><div className="user-message"><p>Can I afford ?28,000/month rent based on this payslip?</p><FileChip sample/><time>10:24 AM</time></div><span className="user-avatar" aria-label="Sample user"><span/></span></div>
          <div className="assistant-row"><ShieldMark className="assistant-avatar"/><div className="assistant-message"><p>Illustrative assistant response ? no document was analyzed.</p><p>Review this example request to preview the approval interface.</p><time>10:24 AM</time></div></div>
          <section className="review-card glass-panel" aria-labelledby="review-title"><div className="review-top"><span className="review-lock"><Icon name="lock" size={28}/></span><div className="review-title"><h2 id="review-title">Review before sending</h2><p>Illustrative cleaned-request preview.</p></div><span className="risk-pill"><i/>LOW RISK ? SAMPLE</span></div><label className="visually-hidden" htmlFor="sanitized-request">Illustrative cleaned request</label><textarea id="sanitized-request" className="request-preview" readOnly={!editing} value={draft} onChange={event => { setDraft(event.target.value); if (notice) setNotice(''); }}/><div className="review-actions"><button className="approve-button" type="button" onClick={() => setNotice('Demo only: no request was sent. Connect the backend to enable reviewed approval.')}><Icon name="send" size={19}/>Approve &amp; get answer</button><button className="edit-button" type="button" onClick={() => { setEditing(!editing); setNotice(editing ? 'Sample preview restored.' : 'Edit the example request. Demo changes are not sent.'); }}><Icon name="edit" size={19}/>{editing ? 'Done editing' : 'Edit request'}</button></div><p className="review-footnote"><span className="info-icon">i</span>Example text only <b>?</b> nothing can be sent from this preview</p></section>
        </> : file ? <><div className="user-row"><div className="user-message"><p>Document selected</p><FileChip file={file} onRemove={removeDocument}/></div></div>{reviewState.review ? <PrivacyReviewPanel state={reviewState} controller={reviewController}/> : <div className="pending-card glass-panel"><span className="pending-icon"><Icon name="lock" size={22}/></span><div><h2>Local analysis unavailable</h2><p>The file is selected in your browser. The backend API is not implemented, so it has not been uploaded, read, or analyzed.</p></div></div>}</> : <EmptyConversation onChoose={() => fileInput.current?.click()}/>}
        {questionState.status === 'processing' && <div className="notice" role="status">Question processing is in progress. <button type="button" onClick={() => { questionController.cancel(); setNotice('Question submission cancelled.'); }}>Cancel</button></div>}
        {questionState.status === 'processing-error' && questionState.error?.retryable && uploadState.uploadedDocument && <div className="notice" role="status">{questionState.error.message} <button type="button" onClick={retryQuestion}>Retry question</button></div>}
        {notice && <p className="notice" role="status">{notice}</p>}
      </div>

      <form className="composer glass-panel" onSubmit={submitQuestion}><input ref={fileInput} className="visually-hidden" type="file" accept="application/pdf,image/png,image/jpeg,image/webp" aria-label="Choose a PDF or image document" onChange={event => selectDocument(event.target.files?.[0])}/><button className="attach-button" type="button" aria-label="Attach a document" onClick={() => fileInput.current?.click()}><Icon name="attach" size={20}/></button><label className="visually-hidden" htmlFor="question">Ask a question about your document</label><textarea id="question" value={question} onChange={event => { setQuestion(event.target.value); questionController.setQuestion(event.target.value); if (notice) setNotice(''); }} placeholder={hasPreview ? 'Ask a follow-up about this sample?' : file ? 'Ask a question about this document?' : 'Choose a document to start a private chat?'} rows="1"/><button className="send-button" type="submit" aria-label="Submit question" disabled={questionState.status === 'processing'}><Icon name="send" size={19}/></button></form>
    </section>

    <aside id="privacy-panel" className="privacy-panel glass-panel" aria-label="Privacy review status">
      <div className="privacy-heading"><span className="privacy-icon"><PrivacyPalLogo size={34}/></span><div><h2>Privacy check</h2><p>{hasPreview ? 'Illustrative sample results ? not an actual analysis.' : 'Local privacy checks will appear here after backend analysis.'}</p></div></div>
      <div className="summary-grid"><div className="summary-card"><span className="summary-symbol warning"><Icon name="eyeOff" size={19}/></span><div><strong>{hasPreview ? '3' : '?'}</strong><p>{hasPreview ? 'details removed' : 'details to review'}</p></div><small>{hasPreview ? 'Sample: name, PAN, account no.' : 'No analysis performed'}</small></div><div className="summary-card"><span className="summary-symbol violet"><Icon name="file" size={18}/></span><div><strong>{hasPreview ? '2' : '?'}</strong><p>{hasPreview ? 'useful facts kept' : 'facts selected'}</p></div><small>{hasPreview ? 'Illustrative sample' : 'No analysis performed'}</small></div></div>
      <ReviewTimeline mode={mode}/>
      <div className="control-note"><span className="note-lock"><Icon name="lock" size={24}/></span><div><strong>You?re in control</strong><p>{hasPreview ? 'This is only a preview. In the real flow, nothing is sent until you approve the exact reviewed text.' : 'Nothing is sent. The backend must be connected before a request can be reviewed or approved.'}</p></div></div>
    </aside>
  </main>;
}

export default App;
