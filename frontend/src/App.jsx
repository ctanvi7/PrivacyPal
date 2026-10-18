import { useEffect, useId, useReducer, useRef, useState } from 'react';
import { createDocumentUploadController } from './lib/documentUploadController.js';
import { createQuestionController } from './lib/questionController.js';
import { adaptBackendWorkflow, createPrivacyReviewController } from './lib/privacyReview.js';
import { privacyPalApi } from './lib/privacyPalApi.js';
import { getPrivacyProgress } from './lib/privacyProgress.js';
import { createInitialWorkflowState, workflowReducer } from './lib/workflow.js';
import { createConversationHistoryController, groupConversationsByLocalDate } from './lib/conversationHistory.js';
import PrivacyReviewPanel from './components/PrivacyReviewPanel.jsx';

const SAMPLE_REQUEST = 'Monthly take-home pay: ₹72,000\nPlanned rent: ₹28,000 per month\nQuestion: Is this rent affordable as a share of monthly income?';
const SARVAM_LANGUAGES = [['en-IN', 'English'], ['hi-IN', 'Hindi'], ['bn-IN', 'Bengali'], ['ta-IN', 'Tamil'], ['te-IN', 'Telugu'], ['mr-IN', 'Marathi'], ['gu-IN', 'Gujarati'], ['kn-IN', 'Kannada'], ['ml-IN', 'Malayalam'], ['pa-IN', 'Punjabi'], ['od-IN', 'Odia'], ['as-IN', 'Assamese'], ['ur-IN', 'Urdu'], ['brx-IN', 'Bodo'], ['doi-IN', 'Dogri'], ['kok-IN', 'Konkani'], ['ks-IN', 'Kashmiri'], ['mai-IN', 'Maithili'], ['mni-IN', 'Manipuri'], ['ne-IN', 'Nepali'], ['sa-IN', 'Sanskrit'], ['sat-IN', 'Santali'], ['sd-IN', 'Sindhi']];
const SARVAM_SPEECH_LANGUAGES = SARVAM_LANGUAGES.slice(0, 11);

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

function FileChip({ file, sample = false, uploaded = false, onRemove }) {
  const name = sample ? 'October payslip.pdf' : file.name;
  const size = sample ? '195 KB · sample document' : `${Math.max(1, Math.round(file.size / 1024))} KB · ${uploaded ? 'confirmed by local service' : 'selected in this browser'}`;
  return <div className="file-chip"><span className="file-icon">PDF</span><span className="file-name"><strong title={name}>{name}</strong><small>{size}</small></span>{sample ? <span className="sample-x" aria-hidden="true"><Icon name="close" size={18}/></span> : <button type="button" className="icon-button" aria-label="Remove selected document" onClick={onRemove}><Icon name="close" size={18}/></button>}</div>;
}

function ReviewTimeline({ mode, uploadStatus, questionStatus, workflowResponse, reviewStatus, answerReturned }) {
  const sample = mode === 'preview';
  const steps = getPrivacyProgress({ uploadStatus, questionStatus, workflowResponse, reviewStatus, answerReturned, illustrativePreview: sample });
  const symbols = { completed: <Icon name="check" size={16}/>, failed: <Icon name="close" size={15}/> };
  return <div className={`review-steps ${sample ? 'is-sample' : ''}`} aria-label={sample ? 'Illustrative workflow progress' : 'Privacy workflow progress'}>{steps.map((step, index) => <div className="timeline-item" data-status={step.status} key={step.id}>
    <span className={`step-number ${step.status}`} data-status={step.status} role="img" aria-label={`${step.title}: ${step.status}`} title={step.status}>{symbols[step.status] || index + 1}</span>
    <div><strong>{step.title}</strong><p>{step.detail}</p></div>
  </div>)}</div>;
}

function EmptyConversation({ onChoose }) {
  return <div className="empty-state"><div className="empty-shield"><ShieldEmblem size={36}/></div><h2>What would you like to understand?</h2><p>Choose a document, then ask a question. You’ll review what may be shared before anything is sent to an AI provider.</p><button className="upload-cta" type="button" onClick={onChoose}><Icon name="attach" size={19}/>Choose a document</button><span className="supported">PDF, PNG, JPEG, or WebP</span><div className="empty-reassurance"><ShieldMark/><p>Your original document stays on this device. Any approved request sent to an external provider will be shown for review first.</p></div></div>;
}

function SavedMessages({ messages, answerResult = null }) {
  const answerIndex = answerResult?.answer ? messages.map(message => message.role === 'assistant' && message.content === answerResult.answer).lastIndexOf(true) : -1;
  return messages.map((message, index) => <div className={message.role === 'user' ? 'user-row' : 'assistant-row'} key={message.message_id}>
    {message.role === 'assistant' && <ShieldMark className="assistant-avatar"/>}
    <div className={message.role === 'user' ? 'user-message history-message' : 'assistant-message history-message'}><p>{message.content}</p>{index === answerIndex && answerResult.pages_used?.length > 0 && <p className="answer-citation">Source pages: {answerResult.pages_used.join(', ')}</p>}<time>{new Date(message.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</time></div>
  </div>);
}

function App() {
  const fileInput = useRef(null);
  const [historyController] = useState(() => createConversationHistoryController({ api: privacyPalApi }));
  const [historyState, setHistoryState] = useState(historyController.getState);
  const [uploadController] = useState(() => createDocumentUploadController({
    createSession: options => privacyPalApi.createSession(options),
    getConversationId: () => historyController.getState().selectedId,
    uploadDocument: (sessionId, selectedFile, options) => privacyPalApi.uploadDocument(sessionId, selectedFile, options),
  }));
  const [uploadState, setUploadState] = useState(uploadController.getState);
  const uploadStateRef = useRef(uploadState);
  uploadStateRef.current = uploadState;
  const [providerOptions, setProviderOptions] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState('default');
  const selectedProviderRef = useRef(selectedProvider);
  selectedProviderRef.current = selectedProvider;
  const [voiceFile, setVoiceFile] = useState(null);
  const [voiceConsent, setVoiceConsent] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState('');
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [translationLanguage, setTranslationLanguage] = useState('hi-IN');
  const [translationSourceLanguage, setTranslationSourceLanguage] = useState('en-IN');
  const [speechLanguage, setSpeechLanguage] = useState('hi-IN');
  const [answerConsent, setAnswerConsent] = useState(false);
  const [speechConsent, setSpeechConsent] = useState(false);
  const [answerTranslation, setAnswerTranslation] = useState('');
  const [answerAudio, setAnswerAudio] = useState('');
  const voiceInput = useRef(null);
  const voiceRecorder = useRef(null);
  const voiceStream = useRef(null);
  const voiceChunks = useRef([]);
  const voiceRecordingTimer = useRef(null);
  const [questionController] = useState(() => createQuestionController({ timeoutMs: 135_000,
    submitQuestion: (text, document, { signal, session }) => privacyPalApi.submitQuestion(session.session_id, document.document_id, text, { signal, providerId: selectedProviderRef.current }),
  }));
  const [questionState, setQuestionState] = useState(questionController.getState);
  const [reviewController] = useState(() => createPrivacyReviewController({
    adaptBackendReview: adaptBackendWorkflow,
    updateDraft: ({ workflowId, version, draft }, options) => {
      const sessionId = uploadStateRef.current.session?.session_id;
      return privacyPalApi.updateDraft(sessionId, workflowId, version, draft, options);
    },
    acknowledgeReview: ({ workflowId, version }, options) => {
      const sessionId = uploadStateRef.current.session?.session_id;
      return privacyPalApi.acknowledgeReview(sessionId, workflowId, version, options);
    },
    sendApprovedRequest: ({ workflowId, version }, options) => {
      const sessionId = uploadStateRef.current.session?.session_id;
      return privacyPalApi.approveWorkflow(sessionId, workflowId, version, options);
    },
  }));
  const [reviewState, setReviewState] = useState(reviewController.getState);
  const handledAnswerRef = useRef(null);
  const [workflow, dispatchWorkflow] = useReducer(workflowReducer, undefined, createInitialWorkflowState);
  const [mode, setMode] = useState('empty');
  const [question, setQuestion] = useState('');
  const [draft, setDraft] = useState(SAMPLE_REQUEST);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState('');
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const [mobilePrivacyOpen, setMobilePrivacyOpen] = useState(false);
  const file = uploadState.selectedFile;

  useEffect(() => uploadController.subscribe(setUploadState), [uploadController]);
  useEffect(() => questionController.subscribe(setQuestionState), [questionController]);
  useEffect(() => reviewController.subscribe(setReviewState), [reviewController]);
  useEffect(() => historyController.subscribe(setHistoryState), [historyController]);
  useEffect(() => { void historyController.load(); }, [historyController]);
  useEffect(() => {
    let active = true;
    void privacyPalApi.listProviders().then(({ items }) => {
      if (!active) return;
      setProviderOptions(items);
      if (items.length && !items.some(item => item.id === selectedProviderRef.current)) setSelectedProvider(items[0].id);
    }).catch(() => { if (active) setProviderOptions([]); });
    return () => { active = false; };
  }, []);
  useEffect(() => { setVoiceConsent(false); setVoiceError(''); }, [voiceFile]);
  useEffect(() => () => {
    if (voiceRecordingTimer.current) clearTimeout(voiceRecordingTimer.current);
    if (voiceRecorder.current?.state === 'recording') voiceRecorder.current.stop();
    voiceStream.current?.getTracks().forEach(track => track.stop());
  }, []);
  useEffect(() => {
    setAnswerConsent(false); setSpeechConsent(false); setAnswerTranslation(''); setAnswerAudio('');
  }, [reviewState.result?.workflow_id, reviewState.result?.answer]);
  useEffect(() => {
    if (mobilePrivacyOpen) document.getElementById('privacy-panel')?.scrollIntoView({ behavior: 'auto', block: 'start' });
  }, [mobilePrivacyOpen]);
  useEffect(() => {
    const result = reviewState.result;
    if (reviewState.status !== 'sent' || !result || handledAnswerRef.current === result.workflow_id) return;
    handledAnswerRef.current = result.workflow_id;
    const conversationId = uploadState.session?.conversation_id || historyState.selectedId;
    void historyController.refreshAfterAnswer(conversationId, result);
    if (result.history_saved) {
      setNotice('Answer returned and saved to this conversation.');
    } else {
      setNotice('Answer returned, but local conversation history could not save this exchange. It will not appear in saved history.');
    }
  }, [reviewState.result, reviewState.status, uploadState.session, historyState.selectedId, historyController]);

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

  function openPreview() { historyController.clearSelection(); uploadController.reset(); questionController.reset(); reviewController.reset(); dispatchWorkflow({ type: 'RESET' }); setMode('preview'); setQuestion(''); setEditing(false); setDraft(SAMPLE_REQUEST); setNotice('This conversation contains illustrative sample data only.'); if (fileInput.current) fileInput.current.value = ''; }

  async function startNewChat() {
    if (historyController.getState().creating) return;
    setMobileHistoryOpen(false);
    uploadController.reset();
    questionController.reset();
    reviewController.reset();
    dispatchWorkflow({ type: 'RESET' });
    setMode('empty');
    setDraft(SAMPLE_REQUEST);
    setEditing(false);
    setQuestion('');
    historyController.clearSelection();
    setNotice('Creating a new conversation…');
    if (fileInput.current) fileInput.current.value = '';
    try {
      await historyController.create();
      setNotice('New conversation ready. Choose a document to begin.');
    } catch {
      setNotice(historyController.getState().error || 'A new conversation could not be created. Try again.');
    }
  }

  async function selectConversation(conversationId) {
    setMobileHistoryOpen(false);
    uploadController.reset();
    questionController.reset();
    reviewController.reset();
    dispatchWorkflow({ type: 'RESET' });
    setQuestion('');
    setMode('history');
    setNotice('');
    if (fileInput.current) fileInput.current.value = '';
    await historyController.open(conversationId);
  }

  async function deleteConversation(conversationId) {
    if (!window.confirm('Delete this saved conversation and its messages? This cannot be undone.')) return;
    const selectedAtDelete = historyController.getState().selectedId === conversationId;
    const deleted = await historyController.remove(conversationId);
    if (deleted && selectedAtDelete && historyController.getState().selectedId === null) {
      uploadController.reset(); questionController.reset(); reviewController.reset();
      dispatchWorkflow({ type: 'RESET' }); setQuestion(''); setMode('empty');
      setNotice('Saved conversation deleted.');
    }
  }

  async function selectDocument(candidate) {
    if (!candidate) return;
    let targetConversationId = historyController.getState().selectedId;
    if (!targetConversationId) {
      try { targetConversationId = (await historyController.create()).conversation_id; }
      catch { setNotice(historyController.getState().error || 'A conversation could not be created. The document was not uploaded.'); if (fileInput.current) fileInput.current.value = ''; return; }
    }
    if (historyController.getState().selectedId !== targetConversationId) {
      setNotice('Conversation selection changed. Choose the document again in the active conversation.');
      if (fileInput.current) fileInput.current.value = '';
      return;
    }
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
    setNotice('Creating a private session and uploading your document…');
    const confirmed = await uploadController.upload();
    if (uploadController.getState().selectedFile !== candidate) return;
    const uploadResult = uploadController.getState();
    setNotice(confirmed
      ? 'Document uploaded and confirmed by the local service. Ask a question to start local privacy analysis.'
      : uploadResult.error?.message || 'The document was not confirmed by the local service.');
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
    reviewController.reset();
    await questionController.submit({ question, uploadedDocument: uploadState.uploadedDocument, session: uploadState.session, uploadedSessionId: uploadState.uploadedSessionId });
    const submission = questionController.getState();
    if (submission.result) {
      reviewController.load(submission.result, { source: 'backend' });
      setNotice('Local privacy analysis returned. Review the exact backend-provided request below; no answer request has been sent.');
    } else if (submission.error) setNotice(submission.error.message);
  }

  async function retryQuestion() {
    await questionController.retry({ uploadedDocument: uploadState.uploadedDocument, session: uploadState.session, uploadedSessionId: uploadState.uploadedSessionId });
    const submission = questionController.getState();
    if (submission.result) reviewController.load(submission.result, { source: 'backend' });
    setNotice(submission.error?.message || 'Question processing completed.');
  }

  async function restartReview() {
    reviewController.reset();
    questionController.setQuestion(question);
    await questionController.submit({ question, uploadedDocument: uploadState.uploadedDocument, session: uploadState.session, uploadedSessionId: uploadState.uploadedSessionId });
    const submission = questionController.getState();
    if (submission.result) reviewController.load(submission.result, { source: 'backend' });
    setNotice(submission.error?.message || 'A fresh local review is ready.');
  }

  async function translateReviewedDraft(sourceLanguage, targetLanguage) {
    const response = reviewController.getState().backendResponse;
    const sessionId = uploadStateRef.current.session?.session_id;
    if (!response || !sessionId) throw new Error('The active reviewed request is unavailable.');
    return privacyPalApi.translateDraft(sessionId, response.workflow_id, response.version, sourceLanguage, targetLanguage);
  }

  async function useTranslatedDraft(text) {
    reviewController.beginEditing();
    reviewController.updateOutgoingText(text);
    await reviewController.finishEditing();
    setNotice('Translated request saved. Privacy checks ran again; review the new exact text before approval.');
  }

  async function startVoiceRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === 'undefined') {
      setVoiceError('This browser does not support microphone recording. Choose an audio file instead.');
      return;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = window.MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : window.MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
      const recorder = new window.MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      voiceChunks.current = [];
      voiceStream.current = stream;
      voiceRecorder.current = recorder;
      setVoiceFile(null);
      setVoiceConsent(false);
      setVoiceError('');
      recorder.ondataavailable = event => {
        if (event.data?.size) voiceChunks.current.push(event.data);
      };
      recorder.onerror = () => setVoiceError('Microphone recording failed. Please try again or choose an audio file.');
      recorder.onstop = () => {
        if (voiceRecordingTimer.current) clearTimeout(voiceRecordingTimer.current);
        voiceRecordingTimer.current = null;
        const audioType = recorder.mimeType || 'audio/webm';
        const audioBlob = new Blob(voiceChunks.current, { type: audioType });
        voiceStream.current?.getTracks().forEach(track => track.stop());
        voiceStream.current = null;
        voiceRecorder.current = null;
        setVoiceRecording(false);
        if (!audioBlob.size) {
          setVoiceError('No audio was recorded. Please try again.');
        } else if (audioBlob.size > 10 * 1024 * 1024) {
          setVoiceError('The recording exceeds the 10 MiB limit. Please record a shorter message.');
        } else {
          setVoiceFile(new File([audioBlob], 'privacypal-dictation.webm', { type: audioType }));
        }
      };
      recorder.start();
      setVoiceRecording(true);
      voiceRecordingTimer.current = setTimeout(() => {
        if (recorder.state === 'recording') {
          setVoiceError('Recording stopped at the 30-second limit. Review it, then choose whether to send it for transcription.');
          recorder.stop();
        }
      }, 30_000);
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop());
      setVoiceRecording(false);
      setVoiceError(error?.name === 'NotAllowedError'
        ? 'Microphone access was denied. Allow microphone access in your browser, or choose an audio file instead.'
        : 'Could not start microphone recording. Check that a microphone is connected, or choose an audio file instead.');
    }
  }

  function stopVoiceRecording() {
    if (voiceRecordingTimer.current) clearTimeout(voiceRecordingTimer.current);
    voiceRecordingTimer.current = null;
    if (voiceRecorder.current?.state === 'recording') voiceRecorder.current.stop();
  }

  async function transcribeSelectedAudio() {
    const sessionId = uploadState.session?.session_id;
    if (!sessionId || !voiceFile || !voiceConsent) return;
    setVoiceBusy(true); setVoiceError(''); setVoiceConsent(false);
    try {
      const result = await privacyPalApi.transcribeAudio(sessionId, voiceFile);
      setQuestion(result.transcript);
      questionController.setQuestion(result.transcript);
      setVoiceFile(null);
      if (voiceInput.current) voiceInput.current.value = '';
      setNotice('Transcript ready. Review or edit the text in the question box before submitting it.');
    } catch (error) { setVoiceError(error?.message || 'Speech transcription failed.'); }
    finally { setVoiceBusy(false); }
  }

  async function translateDisplayedAnswer() {
    const sessionId = uploadState.session?.session_id;
    const answer = reviewState.result?.answer;
    if (!sessionId || !answer || !answerConsent) return;
    setVoiceBusy(true); setVoiceError(''); setAnswerTranslation(''); setAnswerConsent(false);
    try {
      const result = await privacyPalApi.translateAnswer(sessionId, answer, translationSourceLanguage, translationLanguage);
      setAnswerTranslation(result.translated_text);
    } catch (error) { setVoiceError(error?.message || 'Answer translation failed.'); }
    finally { setVoiceBusy(false); }
  }

  async function speakDisplayedAnswer() {
    const sessionId = uploadState.session?.session_id;
    const answer = reviewState.result?.answer;
    if (!sessionId || !answer || !speechConsent) return;
    setVoiceBusy(true); setVoiceError(''); setAnswerAudio(''); setSpeechConsent(false);
    try {
      const result = await privacyPalApi.synthesizeSpeech(sessionId, answer, speechLanguage);
      setAnswerAudio(`data:${result.content_type};base64,${result.audio_base64}`);
    } catch (error) { setVoiceError(error?.message || 'Speech generation failed.'); }
    finally { setVoiceBusy(false); }
  }

  const hasPreview = mode === 'preview';
  const historyGroups = groupConversationsByLocalDate(historyState.items);
  const conversationGroups = [
    ['Today', historyGroups.today],
    ['Previous 7 days', historyGroups.previous7Days],
    ['Older', historyGroups.older],
  ];

  return <main className="workspace" data-workflow-state={workflow.status} data-upload-state={uploadState.status} data-question-state={questionState.status}>
    <aside id="conversation-sidebar" className={`sidebar glass-panel ${mobileHistoryOpen ? 'mobile-open' : ''}`} aria-label="Conversation navigation">
      <a className="brand" href="#home" onClick={event => { event.preventDefault(); startNewChat(); }} aria-label="PrivacyPal home"><span className="brand-mark"><PrivacyPalLogo size={40}/></span><span><strong>PrivacyPal</strong><small>Privacy in your control.</small></span></a>
      <button className="new-chat" type="button" onClick={startNewChat}><span className="plus-disc"><Icon name="plus" size={20}/></span><b>New chat</b><kbd>Ctrl N</kbd></button>
      <nav className="recent-list" aria-label="Conversation navigation">
        {historyState.status === 'loading' && <p className="recent-empty" role="status">Loading saved conversations…</p>}
        {historyState.status === 'error' && <div className="recent-empty" role="alert">{historyState.error} <button type="button" onClick={() => void historyController.refresh()}>Retry</button></div>}
        {historyState.status === 'ready' && historyState.error && <p className="recent-empty" role="alert">{historyState.error}</p>}
        {historyState.status === 'ready' && historyState.items.length === 0 && <p className="recent-empty">No saved conversations</p>}
        {conversationGroups.map(([label, items]) => items.length > 0 && <section key={label} aria-label={label}>
          <p className={`nav-label ${label === 'Previous 7 days' ? 'previous-label' : ''}`}>{label}</p>
          {items.map(item => <div className="history-row" key={item.conversation_id}>
            <button className={`recent ${historyState.selectedId === item.conversation_id ? 'active' : ''}`} type="button" onClick={() => void selectConversation(item.conversation_id)} aria-current={historyState.selectedId === item.conversation_id ? 'page' : undefined}>
              <Icon name="chat" size={18}/><span>{item.preview || 'New conversation'}<small>{new Date(item.updated_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</small></span>
            </button>
            <button className="history-delete" type="button" aria-label={`Delete conversation ${item.preview || 'without a title'}`} disabled={historyState.deletingId === item.conversation_id} onClick={() => void deleteConversation(item.conversation_id)}><Icon name="close" size={16}/></button>
          </div>)}
        </section>)}
        {historyState.status === 'ready' && historyState.hasMore && <button className="history-more" type="button" onClick={() => void historyController.loadMore()}>Load more</button>}
        <p className="nav-label preview-label">Illustrative preview</p>
        <button className={`recent ${hasPreview ? 'active' : ''}`} type="button" onClick={openPreview}><Icon name="chat" size={18}/><span>Rent affordability <small className="recent-sample">Demo content · not saved</small></span></button>
      </nav>
      <div className="local-status"><span className="gemma-icon" aria-hidden="true"><Icon name="cube" size={35}/></span><div><strong>Local analysis · {uploadState.status === 'uploaded' ? 'ready' : 'backend'}</strong><p>{uploadState.status === 'uploaded' ? 'Document confirmed by local service.' : 'Document and question processing run through the local backend.'}</p></div><span className="status-orb" aria-label={uploadState.status === 'uploaded' ? 'Document ready' : 'Local backend status'}/></div>
      <div className="side-links"><button type="button" onClick={() => setNotice('Settings are not available in this frontend yet.')}><Icon name="settings" size={18}/>Settings</button><button type="button" onClick={() => setNotice('Help and feedback are not connected yet.')}><span className="help-icon"><Icon name="help" size={14}/></span>Help &amp; feedback</button></div>
    </aside>

    <section className="chat-column" aria-label="Private chat">
      <header className="chat-header"><div><div className="title-row"><h1>Private chat</h1><span className="local-badge"><Icon name="monitor" size={18}/>Local analysis</span></div><p>Get helpful answers from AI, with your privacy in control.</p><span className={`connection-label ${hasPreview ? 'sample' : ''}`}>{hasPreview ? 'Illustrative preview · demo data only' : uploadState.status === 'uploaded' ? 'Local backend connected · document ready' : 'Local backend integration enabled'}</span></div><div className="mobile-header-actions"><button className="mobile-history" type="button" aria-controls="conversation-sidebar" aria-expanded={mobileHistoryOpen} onClick={() => setMobileHistoryOpen(open => !open)}>{mobileHistoryOpen ? 'Hide history' : 'History'}</button><button className="mobile-privacy" type="button" aria-controls="privacy-panel" aria-expanded={mobilePrivacyOpen} onClick={() => setMobilePrivacyOpen(open => !open)}>{mobilePrivacyOpen ? 'Hide privacy details' : 'Privacy details'}</button></div></header>

      <div className={`conversation ${hasPreview ? 'sample-conversation' : 'empty-conversation'}`} aria-live="polite">
        {hasPreview ? <>
          <div className="user-row"><div className="user-message"><p>Can I afford ₹28,000/month rent based on this payslip?</p><FileChip sample/><time>10:24 AM</time></div><span className="user-avatar" aria-label="Sample user"><span/></span></div>
          <div className="assistant-row"><ShieldMark className="assistant-avatar"/><div className="assistant-message"><p>Illustrative assistant response · no document was analyzed.</p><p>Review this example request to preview the approval interface.</p><time>10:24 AM</time></div></div>
          <section className="review-card glass-panel" aria-labelledby="review-title"><div className="review-top"><span className="review-lock"><Icon name="lock" size={28}/></span><div className="review-title"><h2 id="review-title">Review before sending</h2><p>Illustrative cleaned-request preview.</p></div><span className="risk-pill"><i/>LOW RISK · SAMPLE</span></div><label className="visually-hidden" htmlFor="sanitized-request">Illustrative cleaned request</label><textarea id="sanitized-request" className="request-preview" readOnly={!editing} value={draft} onChange={event => { setDraft(event.target.value); if (notice) setNotice(''); }}/><div className="review-actions"><button className="approve-button" type="button" onClick={() => setNotice('Demo only: no request was sent. Connect the backend to enable reviewed approval.')}><Icon name="send" size={19}/>Approve &amp; get answer</button><button className="edit-button" type="button" onClick={() => { setEditing(!editing); setNotice(editing ? 'Sample preview restored.' : 'Edit the example request. Demo changes are not sent.'); }}><Icon name="edit" size={19}/>{editing ? 'Done editing' : 'Edit request'}</button></div><p className="review-footnote"><span className="info-icon">i</span>Example text only <b>·</b> nothing can be sent from this preview</p></section>
        </> : mode === 'history' ? <>
          {historyState.detailStatus === 'loading' && <p className="notice" role="status">Loading saved conversation…</p>}
          {historyState.detailStatus === 'error' && <div className="pending-card glass-panel" role="alert"><div><h2>Conversation unavailable</h2><p>{historyState.detailError}</p><button className="edit-button" type="button" onClick={() => void historyController.open(historyState.selectedId)}>Retry loading</button></div></div>}
          {historyState.detailStatus === 'ready' && historyState.detail?.messages.length === 0 && <div className="pending-card glass-panel"><div><h2>No saved messages yet</h2><p>This conversation is ready. Choose a document to start a new exchange.</p></div></div>}
          {historyState.detailStatus === 'ready' && historyState.detail?.messages && <SavedMessages messages={historyState.detail.messages}/>}
        </> : file ? <>
          {historyState.detailStatus === 'ready' && historyState.detail?.conversation_id === uploadState.session?.conversation_id && !(reviewState.status === 'sent' && reviewState.result?.history_saved) && <SavedMessages messages={historyState.detail.messages}/>}
          <div className="user-row"><div className="user-message"><p>{uploadState.status === 'uploaded' ? 'Document uploaded' : uploadState.status === 'uploading' ? 'Uploading document' : 'Document selected'}</p><FileChip file={file} uploaded={uploadState.status === 'uploaded'} onRemove={removeDocument}/></div></div>
          {reviewState.status === 'sent' && reviewState.result?.history_saved ? <SavedMessages messages={historyState.detail?.messages || []} answerResult={reviewState.result}/> : <>
            {questionState.question && <div className="user-row"><div className="user-message"><p>{questionState.question}</p></div></div>}
            {questionState.result ? <PrivacyReviewPanel state={reviewState} controller={reviewController} onRestart={restartReview} onTranslate={translateReviewedDraft} onUseTranslation={useTranslatedDraft} sarvamAvailable={providerOptions.some(item => item.id === 'sarvam')}/> : <div className="pending-card glass-panel"><span className="pending-icon"><Icon name="lock" size={22}/></span><div><h2>{uploadState.status === 'uploading' ? 'Uploading to local service' : uploadState.status === 'upload-error' || uploadState.status === 'cancelled' ? 'Upload needs attention' : 'Ready for your question'}</h2><p>{uploadState.status === 'uploading' ? 'Creating a session and processing the selected file. Please wait.' : uploadState.status === 'uploaded' ? 'The local service confirmed this document. Ask a question to run local privacy analysis; this step does not send anything to an answer provider.' : uploadState.error?.message || 'The selected file remains local until the service confirms a successful upload.'}</p>{uploadState.status === 'uploading' && <button className="edit-button" type="button" onClick={() => uploadController.cancel()}>Cancel upload</button>}{uploadState.error?.retryable && <button className="edit-button" type="button" onClick={() => uploadController.retry()}>Retry upload</button>}</div></div>}
            {reviewState.result?.answer && <div className="assistant-row"><ShieldMark className="assistant-avatar"/><div className="assistant-message"><p>{reviewState.result.answer}</p>{reviewState.result.pages_used?.length > 0 && <p className="answer-citation">Source pages: {reviewState.result.pages_used.join(', ')}</p>}<time>Answer returned by the backend</time>{providerOptions.some(item => item.id === 'sarvam') && <section className="sarvam-answer-tools" aria-label="Optional Sarvam translation and speech"><label>Source language <select value={translationSourceLanguage} onChange={event => setTranslationSourceLanguage(event.target.value)}>{SARVAM_LANGUAGES.map(([code, name]) => <option key={`source-${code}`} value={code}>{name}</option>)}</select></label><label>Translation language <select value={translationLanguage} onChange={event => setTranslationLanguage(event.target.value)}>{SARVAM_LANGUAGES.map(([code, name]) => <option key={`target-${code}`} value={code}>{name}</option>)}</select></label><label className="sarvam-consent"><input type="checkbox" checked={answerConsent} onChange={event => setAnswerConsent(event.target.checked)}/> Send this displayed answer to Sarvam for translation.</label><button className="edit-button" type="button" disabled={!answerConsent || voiceBusy} onClick={() => void translateDisplayedAnswer()}>{voiceBusy ? 'Working…' : 'Translate answer'}</button>{answerTranslation && <p className="translated-answer">{answerTranslation}</p>}<label>Speech language <select value={speechLanguage} onChange={event => setSpeechLanguage(event.target.value)}>{SARVAM_SPEECH_LANGUAGES.map(([code, name]) => <option key={`speech-${code}`} value={code}>{name}</option>)}</select></label><label className="sarvam-consent"><input type="checkbox" checked={speechConsent} onChange={event => setSpeechConsent(event.target.checked)}/> Send this displayed answer text to Sarvam to create audio.</label><button className="edit-button" type="button" disabled={!speechConsent || voiceBusy} onClick={() => void speakDisplayedAnswer()}>Read answer aloud</button>{answerAudio && <audio controls src={answerAudio}>Audio playback is not supported by this browser.</audio>}{voiceError && <p role="alert">{voiceError}</p>}</section>}</div></div>}
          </>}
        </> : <EmptyConversation onChoose={() => fileInput.current?.click()}/>}

        {questionState.status === 'processing' && <div className="notice" role="status">Question processing is in progress. <button type="button" onClick={() => { questionController.cancel(); setNotice('Question submission cancelled.'); }}>Cancel</button></div>}
        {questionState.status === 'processing-error' && questionState.error?.retryable && uploadState.uploadedDocument && <div className="notice" role="status">{questionState.error.message} <button type="button" onClick={retryQuestion}>Retry question</button></div>}
        {notice && <p className="notice" role="status">{notice}</p>}
      </div>

        {providerOptions.length > 0 && <div className="provider-choice"><label htmlFor="answer-provider">Answer provider</label><select id="answer-provider" value={selectedProvider} disabled={questionState.status === 'processing' || Boolean(questionState.result)} onChange={event => setSelectedProvider(event.target.value)}>{providerOptions.map(provider => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select><span>The selected provider receives only the exact reviewed request after approval.</span></div>}
        <form className="composer glass-panel" onSubmit={submitQuestion}><input ref={fileInput} className="visually-hidden" type="file" accept="application/pdf,image/png,image/jpeg,image/webp" aria-label="Choose a PDF or image document" onChange={event => selectDocument(event.target.files?.[0])}/><button className="attach-button" type="button" aria-label="Attach a document" onClick={() => fileInput.current?.click()} disabled={uploadState.status === 'uploading' || questionState.status === 'processing'}><Icon name="attach" size={20}/></button><label className="visually-hidden" htmlFor="question">Ask a question about your document</label><textarea id="question" value={question} onChange={event => { setQuestion(event.target.value); questionController.setQuestion(event.target.value); if (notice) setNotice(''); }} placeholder={hasPreview ? 'Ask a follow-up about this sample?' : file ? 'Ask a question about this document?' : 'Choose a document to start a private chat…'} rows="1" disabled={questionState.status === 'processing' || uploadState.status === 'uploading'}/><button className="send-button" type="submit" aria-label="Submit question" disabled={questionState.status === 'processing' || uploadState.status !== 'uploaded' || !question.trim()}><Icon name="send" size={19}/></button></form>
        {providerOptions.some(item => item.id === 'sarvam') && uploadState.session && <section className="voice-input-tools" aria-label="Optional voice dictation"><input ref={voiceInput} className="visually-hidden" type="file" accept="audio/wav,audio/x-wav,audio/mpeg,audio/mp3,audio/aac,audio/flac,audio/ogg,audio/opus,audio/webm,audio/aiff,audio/mp4,video/mp4,.wav,.mp3,.aac,.flac,.ogg,.opus,.webm,.aiff,.m4a,.mp4,.amr,.wma" onChange={event => { setVoiceFile(event.target.files?.[0] || null); setVoiceError(''); }} aria-label="Choose an audio recording"/><p>Dictate a question or choose a recording. Microphone audio stays in this browser until you explicitly consent and select Transcribe. Recordings are limited to 30 seconds and 10 MiB. The transcript appears in the question box for review; it is not submitted automatically.</p>{voiceRecording ? <button className="edit-button" type="button" onClick={stopVoiceRecording} disabled={voiceBusy}>Stop dictation</button> : <button className="edit-button" type="button" onClick={() => void startVoiceRecording()} disabled={voiceBusy}>Start dictation</button>}{voiceRecording && <p role="status">Recording… Select Stop dictation when you are finished.</p>}<button className="edit-button" type="button" onClick={() => voiceInput.current?.click()} disabled={voiceBusy || voiceRecording}>Choose audio file instead</button>{voiceFile && <span>Ready to transcribe: {voiceFile.name}</span>}<label className="sarvam-consent"><input type="checkbox" checked={voiceConsent} onChange={event => setVoiceConsent(event.target.checked)}/> I consent to send this recording to Sarvam for transcription.</label><button className="edit-button" type="button" disabled={!voiceFile || !voiceConsent || voiceBusy || voiceRecording} onClick={() => void transcribeSelectedAudio()}>{voiceBusy ? 'Transcribing…' : 'Transcribe audio'}</button>{voiceError && <p role="alert">{voiceError}</p>}</section>}
    </section>

    <aside id="privacy-panel" className={`privacy-panel glass-panel ${mobilePrivacyOpen ? 'mobile-open' : ''}`} aria-label="Privacy review status">
      <div className="privacy-heading"><span className="privacy-icon"><PrivacyPalLogo size={34}/></span><div><h2>Privacy check</h2><p>{hasPreview ? 'Illustrative sample results · not an actual analysis.' : 'Local privacy checks will appear here after backend analysis.'}</p></div></div>
      <div className="summary-grid"><div className="summary-card"><span className="summary-symbol warning"><Icon name="eyeOff" size={19}/></span><div><strong>{hasPreview ? '3' : questionState.result ? questionState.result.findings.length : '—'}</strong><p>{hasPreview ? 'details removed' : 'findings returned'}</p></div><small>{hasPreview ? 'Sample: name, PAN, account no.' : questionState.result ? 'Backend response' : 'No analysis performed'}</small></div><div className="summary-card"><span className="summary-symbol violet"><Icon name="file" size={18}/></span><div><strong>{hasPreview ? '2' : questionState.result ? questionState.result.pages_used.length : '—'}</strong><p>{hasPreview ? 'useful facts kept' : 'pages used'}</p></div><small>{hasPreview ? 'Illustrative sample' : questionState.result ? 'Backend response' : 'No analysis performed'}</small></div></div>
      <ReviewTimeline mode={mode} uploadStatus={uploadState.status} questionStatus={questionState.status} workflowResponse={questionState.result} reviewStatus={reviewState.status} answerReturned={Boolean(reviewState.result?.answer)}/>
      <div className="control-note"><span className="note-lock"><Icon name="lock" size={24}/></span><div><strong>You’re in control</strong><p>{hasPreview ? 'This is only a preview. In the real flow, nothing is sent until you approve the exact reviewed text.' : reviewState.result?.answer ? 'The backend returned an answer for the exact request you approved.' : questionState.result ? 'Local privacy review is complete; no answer request is sent until you explicitly approve.' : 'Questions are enabled only after the local service confirms the uploaded document.'}</p></div></div>
    </aside>
  </main>;
}

export default App;
