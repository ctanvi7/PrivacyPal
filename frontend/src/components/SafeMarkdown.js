import { createElement as h, Fragment } from 'react';

// A deliberately small Markdown presenter. Content is always React text, never HTML.
// Links are shown as text; images are not fetched from provider-supplied URLs.
function inline(text) {
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|!?\[[^\]\n]*\]\([^\s)]*\))/g;
  const parts = [];
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push(text.slice(offset, match.index));
    const token = match[0];
    const key = match.index;
    if (token.startsWith('`')) parts.push(h('code', { key }, token.slice(1, -1)));
    else if (token.startsWith('**') || token.startsWith('__')) parts.push(h('strong', { key }, token.slice(2, -2)));
    else if (token.startsWith('*') || token.startsWith('_')) parts.push(h('em', { key }, token.slice(1, -1)));
    else parts.push(h(Fragment, { key }, token.slice(token.indexOf('[') + 1, token.indexOf(']'))));
    offset = match.index + token.length;
  }
  parts.push(text.slice(offset));
  return parts;
}

const listItem = line => /^(\s*)([-+*]|\d+[.)])\s+(.+)$/.exec(line);
const isBlock = line => /^\s*(#{1,6}\s|```|~~~|>|(?:[-*_]\s*){3,}$)/.test(line) || listItem(line);

export default function SafeMarkdown({ children = '' }) {
  const lines = String(children).replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const key = index;
    if (!line.trim()) { index += 1; continue; }
    const fence = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fence) {
      const code = [];
      index += 1;
      while (index < lines.length && !lines[index].trimStart().startsWith(fence[1])) code.push(lines[index++]);
      index += 1;
      blocks.push(h('pre', { key }, h('code', null, code.join('\n'))));
      continue;
    }
    const heading = /^\s*(#{1,6})\s+(.+?)(?:\s+#+)?\s*$/.exec(line);
    if (heading) {
      blocks.push(h(`h${Math.min(heading[1].length + 2, 6)}`, { key }, inline(heading[2])));
      index += 1;
      continue;
    }
    if (/^\s*(?:[-*_]\s*){3,}$/.test(line)) {
      blocks.push(h('hr', { key })); index += 1; continue;
    }
    const firstItem = listItem(line);
    if (firstItem) {
      const ordered = /^\d/.test(firstItem[2]);
      const items = [];
      while (index < lines.length) {
        const item = listItem(lines[index]);
        if (!item || /^\d/.test(item[2]) !== ordered) break;
        const content = [item[3]];
        index += 1;
        while (index < lines.length && lines[index].trim() && !isBlock(lines[index])) content.push(lines[index++].trim());
        items.push(h('li', { key: index }, inline(content.join(' '))));
      }
      blocks.push(h(ordered ? 'ol' : 'ul', { key, ...(ordered ? { start: parseInt(firstItem[2], 10) } : {}) }, items));
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, ''));
      blocks.push(h('blockquote', { key }, inline(quote.join(' '))));
      continue;
    }
    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isBlock(lines[index])) paragraph.push(lines[index++]);
    blocks.push(h('p', { key }, inline(paragraph.join('\n'))));
  }
  return h('div', { className: 'answer-markdown' }, blocks);
}
