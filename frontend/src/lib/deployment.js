export const CLOUD_HOSTED = import.meta.env?.VITE_DEPLOYMENT_MODE === 'aws';

// Presentation copy only. Never apply this to drafts, documents, or answers.
export function processingCopy(text) {
  if (!CLOUD_HOSTED || typeof text !== 'string') return text;
  return text.replace(/\blocally\b/g, 'in AWS').replace(/\bLocal\b/g, 'AWS').replace(/\blocal\b/g, 'AWS');
}
