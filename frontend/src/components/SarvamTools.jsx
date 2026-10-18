import { useEffect, useRef, useState } from 'react';
import { privacyPalApi } from '../lib/privacyPalApi.js';
import { CLOUD_HOSTED } from '../lib/deployment.js';
import { MAX_RECORDING_MS, MAX_VOICE_BYTES, SARVAM_LANGUAGES, SARVAM_SPEECH_LANGUAGES } from '../lib/sarvam.js';
import SafeMarkdown from './SafeMarkdown.js';

function Language({ label, value, onChange, speech = false, disabled }) {
  return <label>{label} <select value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>{(speech ? SARVAM_SPEECH_LANGUAGES : SARVAM_LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>;
}

export function VoiceInput({ sessionId, onTranscript, onBusyChange, disabled = false }) {
  const [file, setFile] = useState(null);
  const [consent, setConsent] = useState(false);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const input = useRef(null), recorder = useRef(null), stream = useRef(null), timer = useRef(null), operation = useRef(null), mounted = useRef(true);
  const limit = CLOUD_HOSTED ? 4 * 1024 * 1024 : MAX_VOICE_BYTES;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearTimeout(timer.current); operation.current?.abort();
      if (recorder.current?.state === 'recording') recorder.current.stop();
      stream.current?.getTracks().forEach(track => track.stop());
      onBusyChange(false);
    };
  }, [sessionId, onBusyChange]);
  function choose(candidate) {
    setConsent(false); setError(''); setFile(null);
    if (candidate && (!candidate.size || candidate.size > limit)) setError(`Choose a nonempty recording up to ${limit / 1024 / 1024} MiB.`);
    else setFile(candidate || null);
  }
  async function record() {
    if (busy || recording || disabled) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setError('Microphone recording is unavailable. Choose an audio file instead.'); return; }
    setBusy(true); onBusyChange(true); setError('');
    try {
      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) { audioStream.getTracks().forEach(track => track.stop()); return; }
      stream.current = audioStream;
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => window.MediaRecorder.isTypeSupported(type));
      const current = new window.MediaRecorder(audioStream, mime ? { mimeType: mime } : undefined);
      recorder.current = current;
      const chunks = [];
      current.ondataavailable = event => { if (event.data?.size) chunks.push(event.data); };
      current.onerror = () => { if (mounted.current) setError('Recording failed. Choose an audio file or record again.'); if (current.state === 'recording') current.stop(); };
      current.onstop = () => {
        clearTimeout(timer.current); audioStream.getTracks().forEach(track => track.stop());
        recorder.current = null; stream.current = null;
        if (!mounted.current) return;
        const type = current.mimeType || 'audio/webm';
        choose(new File(chunks, `dictation.${type.includes('mp4') ? 'm4a' : 'webm'}`, { type }));
        setRecording(false); setBusy(false); onBusyChange(false);
      };
      choose(null); current.start(); setRecording(true);
      timer.current = setTimeout(() => { if (current.state === 'recording') current.stop(); }, MAX_RECORDING_MS);
    } catch {
      stream.current?.getTracks().forEach(track => track.stop());
      if (mounted.current) { setBusy(false); onBusyChange(false); setError('Microphone access failed. Allow access or choose an audio file instead.'); }
    }
  }
  async function transcribe() {
    if (!file || !consent || busy || disabled) return;
    setConsent(false); setBusy(true); onBusyChange(true); setError('');
    operation.current = new AbortController();
    try {
      const result = await privacyPalApi.transcribeAudio(sessionId, file, { signal: operation.current.signal });
      if (mounted.current) { onTranscript(result.transcript); choose(null); if (input.current) input.current.value = ''; }
    } catch (failure) { if (mounted.current) setError(failure?.message || 'Transcription failed.'); }
    finally { if (mounted.current) { setBusy(false); onBusyChange(false); } }
  }
  return <details className="voice-input-tools"><summary>Dictate a question</summary><p>Recording stays in your browser until you consent and select Transcribe. Sarvam receives the audio. The transcript is placed in the question box for you to review, and is never submitted automatically. Microphone recordings stop after 30 seconds.</p>
    <input ref={input} type="file" accept="audio/*,.webm,.m4a" aria-label="Choose an audio recording" disabled={busy || disabled} onChange={e => choose(e.target.files?.[0])}/>
    <button type="button" className="edit-button" disabled={disabled || (busy && !recording)} onClick={() => recording ? recorder.current?.stop() : void record()}>{recording ? 'Stop dictation' : 'Start dictation'}</button>
    {recording && <p role="status">Recording…</p>}{file && <p>{file.name}</p>}
    <label className="sarvam-consent"><input type="checkbox" checked={consent} disabled={busy || disabled || !file} onChange={e => setConsent(e.target.checked)}/> Send this recording to Sarvam for transcription.</label>
    <button type="button" className="edit-button" disabled={busy || disabled || !file || !consent} onClick={transcribe}>{busy && !recording ? 'Transcribing…' : 'Transcribe audio'}</button>{error && <p role="alert">{error}</p>}
  </details>;
}

export function AnswerTools({ sessionId, answer, onBusyChange }) {
  const [source, setSource] = useState('en-IN'), [target, setTarget] = useState('hi-IN'), [language, setLanguage] = useState('hi-IN');
  const [translateConsent, setTranslateConsent] = useState(false), [speechConsent, setSpeechConsent] = useState(false);
  const [translation, setTranslation] = useState(''), [audio, setAudio] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const operation = useRef(null), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; operation.current?.abort(); onBusyChange(false); }; }, [sessionId, answer, onBusyChange]);
  useEffect(() => { setTranslateConsent(false); setTranslation(''); }, [source, target]);
  useEffect(() => { setSpeechConsent(false); setAudio(''); }, [language]);
  async function run(speech) {
    if (busy || !(speech ? speechConsent : translateConsent)) return;
    setBusy(true); onBusyChange(true); setError(''); setTranslateConsent(false); setSpeechConsent(false);
    operation.current = new AbortController();
    try {
      const options = { signal: operation.current.signal };
      const result = speech ? await privacyPalApi.synthesizeSpeech(sessionId, answer, language, options) : await privacyPalApi.translateAnswer(sessionId, answer, source, target, options);
      if (mounted.current) { if (speech) setAudio(`data:audio/wav;base64,${result.audio_base64}`); else setTranslation(result.translated_text); }
    } catch (failure) { if (mounted.current) setError(failure?.message || 'Sarvam could not complete this operation.'); }
    finally { if (mounted.current) { setBusy(false); onBusyChange(false); } }
  }
  return <section className="sarvam-answer-tools" aria-label="Optional Sarvam translation and speech"><h3>Translate or listen</h3><p>Each action sends the displayed answer to Sarvam. Your document and conversation history are not attached.</p>
    <Language label="Answer source language" value={source} onChange={setSource} disabled={busy}/><Language label="Answer translation language" value={target} onChange={setTarget} disabled={busy}/>
    <label className="sarvam-consent"><input type="checkbox" checked={translateConsent} disabled={busy || answer.length > 2000} onChange={e => setTranslateConsent(e.target.checked)}/> Send this displayed answer to Sarvam for translation.</label>
    <button type="button" className="edit-button" disabled={busy || !translateConsent || answer.length > 2000} onClick={() => void run(false)}>Translate answer</button>
    {answer.length > 2000 && <p>Answer translation supports up to 2,000 characters.</p>}{translation && <section aria-label="Translated answer"><SafeMarkdown>{translation}</SafeMarkdown></section>}
    <Language label="Speech language" value={language} onChange={setLanguage} speech disabled={busy}/><label className="sarvam-consent"><input type="checkbox" checked={speechConsent} disabled={busy || answer.length > 2500} onChange={e => setSpeechConsent(e.target.checked)}/> Send this displayed answer to Sarvam for speech generation.</label>
    <button type="button" className="edit-button" disabled={busy || !speechConsent || answer.length > 2500} onClick={() => void run(true)}>Read answer aloud</button>
    {answer.length > 2500 && <p>Speech supports up to 2,500 characters.</p>}{audio && <audio controls src={audio} aria-label="Sarvam answer audio"/>}{error && <p role="alert">{error}</p>}
  </section>;
}
