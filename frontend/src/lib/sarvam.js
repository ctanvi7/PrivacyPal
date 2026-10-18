export const SARVAM_LANGUAGES = [
  ['en-IN', 'English'], ['hi-IN', 'Hindi'], ['bn-IN', 'Bengali'], ['ta-IN', 'Tamil'],
  ['te-IN', 'Telugu'], ['mr-IN', 'Marathi'], ['gu-IN', 'Gujarati'], ['kn-IN', 'Kannada'],
  ['ml-IN', 'Malayalam'], ['pa-IN', 'Punjabi'], ['od-IN', 'Odia'], ['as-IN', 'Assamese'],
  ['ur-IN', 'Urdu'], ['brx-IN', 'Bodo'], ['doi-IN', 'Dogri'], ['kok-IN', 'Konkani'],
  ['ks-IN', 'Kashmiri'], ['mai-IN', 'Maithili'], ['mni-IN', 'Manipuri'], ['ne-IN', 'Nepali'],
  ['sa-IN', 'Sanskrit'], ['sat-IN', 'Santali'], ['sd-IN', 'Sindhi'],
];
export const SARVAM_SPEECH_LANGUAGES = SARVAM_LANGUAGES.slice(0, 11);
export const MAX_VOICE_BYTES = 10 * 1024 * 1024;
export const MAX_RECORDING_MS = 30_000;
