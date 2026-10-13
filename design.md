# PrivacyPal Design System

This document is the visual and interaction source of truth for PrivacyPal's interface. Use it when creating or changing screens, components, and responsive layouts.

## Product context

PrivacyPal is a privacy-first AI workspace. It helps a user inspect a document, decide what information is needed, review a sanitized request, and then choose whether to send that request to an external answer model. Gemma runs locally to analyze files and guide privacy decisions. The interface must make each step and destination clear.

### Source of truth

- Follow the product requirements and security documentation for behavior and data handling.
- Follow this file for visual styling, interaction patterns, and layout.
- If visual guidance conflicts with a security or privacy requirement, follow the security requirement and update the interface to communicate it clearly.
- Never imply that data stays on the device after the user approves sending a request to an external provider. Identify the destination before the user approves.

## 1. Design direction

**Style:** Minimal, premium, dark, softly technical, liquid glass.

**Mood:** Calm and capable. The UI should feel trustworthy and precise, with a little warmth from the violet accent. Avoid a cold security dashboard or a playful chatbot aesthetic.

### Design principles

1. **Clarity before atmosphere.** Text, risk levels, destinations, and actions stay readable over every surface effect.
2. **Make privacy decisions visible.** Show what was detected, what will be changed, what will be sent, and where it will go.
3. **Keep control with the user.** Review, edit, approve, or cancel actions are explicit. No sensitive content is sent without an intentional approval step.
4. **Use glass as a material, not decoration.** Reserve translucency, blur, and highlights for interactive surfaces. Keep the main canvas solid and quiet.
5. **Keep the chat central.** The conversation is the main working area. Side panels provide supporting context without competing for attention.
6. **Use color and words together.** Never communicate sensitivity, success, or failure through color alone.

## 2. Brand

**Brand name:** PrivacyPal

**Logo:** Use the product's existing shield or privacy mark with the wordmark. Keep it simple, monochrome or violet-accented, and legible at small sizes. Do not invent alternate marks for individual pages. Use an accessible text label wherever the wordmark is not visible.

**Brand voice:** Direct, reassuring, human, and specific. Explain privacy actions in plain language. Prefer “Review what will be shared” to vague labels such as “Secure mode.” Avoid absolute claims such as “100% safe” or “your data never leaves your device.”

## 3. Color palette

Use the tokens below as the starting palette. For translucent surfaces, pair the listed surface color with the specified border and verify text contrast against the rendered background.

| Token | Value | Use |
|---|---|---|
| `--color-background` | `#07080B` | Solid application canvas |
| `--color-background-raised` | `#0D0F14` | Chat area and raised regions |
| `--color-surface` | `#15171D` | Opaque fallback for glass cards |
| `--color-glass` | `rgba(29, 31, 39, 0.78)` | Sidebar, inspector, cards, and controls |
| `--color-glass-raised` | `rgba(42, 43, 53, 0.82)` | Hovered or elevated glass surfaces |
| `--color-accent` | `#B78AF7` | Primary violet action and selected states |
| `--color-accent-strong` | `#9D5DE8` | Strong emphasis and active control fills |
| `--color-accent-soft` | `#D7BFFF` | Accent text and subtle highlights |
| `--color-text` | `#F5F3F8` | Primary text |
| `--color-text-secondary` | `#C8C4D0` | Supporting text |
| `--color-text-muted` | `#A29DAB` | Metadata and placeholders; check contrast at actual size |
| `--color-border` | `rgba(230, 225, 240, 0.14)` | Default surface border |
| `--color-border-strong` | `rgba(230, 225, 240, 0.24)` | Emphasized boundary or focus-adjacent edge |
| `--color-success` | `#83D6A6` | Completed or approved state |
| `--color-warning` | `#F1C875` | Needs review or caution |
| `--color-error` | `#FF7D88` | Sensitive finding, blocking issue, or failure |

Use violet for the brand and primary action, not as a replacement for semantic status colors. Redaction and sensitive findings must include a text label or icon as well as their color. Do not reduce text opacity to create hierarchy when that makes it hard to read.

### Liquid-glass treatment

- Keep the canvas near-black and visually solid.
- Use dark silver-gray surfaces with a subtle translucent fill, a fine light border, and a restrained top-edge highlight.
- Apply backdrop blur only where supported and provide the opaque `--color-surface` fallback.
- Purple appears as a controlled highlight on selected tabs, key actions, and focus states; it should not tint every surface.
- Keep the floating bubble motif faint and confined to the side panels. Bubbles should sit behind panel content, never behind text, status labels, or controls. The center chat remains free of floating bubbles.
- Avoid bright neon glows, large gradients, glossy reflections, and heavy blur that lowers text contrast.

## 4. Typography

**Font family:** Use the bundled `Inter` font if the project already includes it. Otherwise use `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`. Do not fetch fonts from a remote service at runtime.

**Heading font:** Same family as body; use weight and spacing for hierarchy rather than a decorative display face.

**Body font:** Same family. Use a bundled monospace/system monospace stack for exact sanitized request previews, IDs, or code-like material only.

| Style | Size / weight / line height |
|---|---|
| H1 | 32px / 650–700 / 1.15 |
| H2 | 22px / 600–650 / 1.25 |
| H3 | 16px / 600 / 1.35 |
| Body | 14–16px / 400 / 1.5 |
| Small | 12px / 400–500 / 1.4 |
| Button and control label | 14px / 550–600 / 1.2 |

Use sentence case. Avoid long all-caps labels and overly tight letter spacing. Allow user-provided text and filenames to wrap without clipping.

## 5. Spacing

**Base unit:** 4px.

**Spacing scale:** 4, 8, 12, 16, 24, 32, 48, 64, 96px.

Use the scale consistently. Typical component padding is 16–24px; compact controls use 8–12px. Desktop panel gaps are 16–24px. Do not add spacing values ad hoc when a scale value fits.

## 6. Border radius

| Size | Value | Typical use |
|---|---:|---|
| Small | 8px | Chips, compact inputs, small menus |
| Medium | 14px | Buttons, fields, small cards |
| Large | 22px | Chat bubbles and primary cards |
| Extra large | 28px | Main glass panels and prominent review cards |
| Pill | 999px | Status pills and circular icon buttons |

Keep radii consistent within a component family. Do not make every nested element a pill.

## 7. Shadows and surface depth

- **Small:** Fine border plus a restrained inset highlight; use for controls and chips.
- **Medium:** Soft shadow such as `0 10px 30px rgba(0, 0, 0, 0.24)` for floating cards or menus.
- **Large:** Soft, broad shadow such as `0 20px 60px rgba(0, 0, 0, 0.32)` for an overlay that must separate from the workspace.

Shadows should describe elevation, not create a glow. Do not use strong purple shadows on every component. Ensure floating content also has a visible boundary.

## 8. Buttons

All buttons need a clear accessible name, visible hover and focus states, and a minimum 44×44px target where practical.

- **Primary:** Violet fill or restrained violet glass fill, high-contrast label, medium radius. Use for the next explicit step, such as approving a reviewed request. Include the action and destination nearby when relevant.
- **Secondary:** Dark silver glass, fine border, light label. Use for actions such as Edit, Review, or Cancel.
- **Danger:** Transparent or dark surface with an error-colored border and label. Reserve a solid error fill for a destructive confirmation step.
- **Disabled:** Muted surface and label with a visible disabled state. Do not rely on opacity alone; provide a reason when the user needs to understand why the action is unavailable.
- **Loading:** Keep the button width stable, show a small spinner or progress indicator, and use a concise label such as “Analyzing…”. Prevent duplicate submission and expose progress to assistive technology.

Icon-only buttons must have a tooltip or accessible label. Do not place multiple visually competing primary buttons in one decision area.

## 9. Inputs and file controls

- **Default:** Dark translucent fill, subtle silver border, readable label above the field, and a short placeholder that supplements rather than replaces the label.
- **Focus:** Visible 2px violet focus ring with sufficient contrast against the surface. Keep keyboard focus visible.
- **Error:** Error border plus an inline text explanation associated with the input. Preserve the user's entered value where safe.
- **Disabled:** Clearly unavailable with an explanatory label or adjacent reason where needed.
- **Placeholder:** Use muted text that remains readable; never use placeholder text as the only field label.
- **File chip:** Show a file icon, filename, type or status as needed, and a remove action with an accessible name. Long filenames wrap or truncate with a way to inspect the full name.
- **Composer:** Keep the message field visually distinct from the send action. Support keyboard operation and communicate when a file is attached or being analyzed.

## 10. Cards and chat

Cards use a dark glass surface with a fine border, 16–24px internal padding, and a 14–28px radius based on prominence. Provide an opaque surface fallback. Keep card nesting shallow; avoid stacking glass on glass repeatedly.

### Conversation layout

- Assistant and user messages must be visually distinct through alignment, surface, and labels, not color alone.
- Keep the central conversation the strongest visual area. Maintain a comfortable reading width and consistent message spacing.
- Use compact, subtle message surfaces. Reserve larger cards for meaningful workflow steps, such as file review and approval.
- Preserve visible source/file context without exposing more sensitive document content than needed.

### Privacy review card

This is a core product component and must be easy to understand at a glance. It should show:

1. What the local analysis found, with a count and readable categories when available.
2. What content will be removed, replaced, or retained.
3. The exact sanitized request or a clear way to inspect it.
4. The destination model/provider before approval.
5. Explicit actions to edit, approve, or cancel.

Do not imply that Gemma's analysis guarantees the absence of all sensitive information. Keep warnings actionable, and do not send the request until the user approves.

## 11. Navigation and application layout

### Desktop workspace

Use a three-region workspace:

- **Left sidebar:** Approximately 260–300px. Product identity, new chat, recent conversations, and settings. Glass surface with the subtle bubble motif kept behind content.
- **Center workspace:** Flexible and dominant. Chat history, file context, review/approval card, and composer. Keep this region calm and mostly solid.
- **Right privacy panel:** Approximately 320–380px. Local analysis status, findings summary, current privacy step, and destination context. Glass surface with faint background bubbles only.

At narrower desktop widths, reduce side panel widths or allow one panel to collapse before compressing the chat to an unusable width. Use a consistent header height and align panel tops.

### Header

Keep the header compact. Include the active workspace or conversation title and only the most useful global actions. Do not duplicate the sidebar's navigation in the header.

### Mobile navigation

Keep the conversation and its primary action in the foreground. Collapse the left sidebar into a menu or drawer. Move privacy details into a clearly labeled expandable panel or sheet. Keep review and destination information available before approval. Avoid horizontal scrolling and do not hide a required privacy decision behind an unlabeled icon.

## 12. States and feedback

- **Loading:** Show the current step (for example, “Reading file locally” or “Preparing privacy review”) and a restrained progress cue. Do not claim progress that the system cannot measure.
- **Empty:** Explain what the user can do next, such as starting a chat or adding a supported file. Use one clear primary action.
- **Error:** State what failed, what data was or was not sent if known, and a useful recovery action. Fail closed when analysis or sanitization cannot be confirmed. Never silently continue to an external model after a privacy step fails.
- **Success:** Confirm the action in plain language and identify the stage completed. Distinguish local analysis from an externally generated answer.
- **Disabled:** Keep the reason discoverable. For approval, explain which required review step is incomplete.
- **Sensitive content:** Use a text label and semantic icon with status color. Avoid displaying the full secret in summaries, logs, or error messages.

## 13. Icons

**Icon library:** Prefer the icon library already used in the codebase. If none exists, use small inline SVG icons with consistent stroke geometry rather than adding a dependency just for decoration.

**Default size:** 18–20px for controls; 16px for compact metadata; 22–24px for prominent section markers.

**Style:** Rounded outline, consistent 1.8–2px stroke, simple silhouettes. Use filled icons only for selected states or status symbols. Avoid emoji and decorative icon clusters.

## 14. Responsive design

Treat these as starting breakpoints and adapt to content:

| Viewport | Behavior |
|---|---|
| Mobile: `< 768px` | One-column conversation; sidebar in a drawer; privacy panel in a labeled sheet or expandable section; controls remain touch-friendly. |
| Tablet: `768–1199px` | Conversation remains primary; sidebar may be compact; privacy panel collapses or moves below the conversation when space is limited. |
| Desktop: `≥ 1200px` | Three-region workspace when there is enough room for readable content. |

Keep the composer reachable, allow content to scroll within the main area, and prevent panels from covering keyboard focus. Test narrow widths and browser zoom. Do not solve overflow by shrinking text below comfortable reading sizes.

## 15. Accessibility

- Use semantic HTML and correct heading hierarchy.
- Meet WCAG AA contrast: at least 4.5:1 for normal text and 3:1 for large text and meaningful UI boundaries. Test translucent surfaces against their actual rendered backgrounds.
- Support complete keyboard navigation, logical focus order, and visible focus states.
- Provide accessible labels for icon-only buttons and form controls.
- Announce loading, completion, and errors with appropriate live regions without repeatedly interrupting the user.
- Do not rely on color alone for sensitivity, status, or action availability.
- Respect `prefers-reduced-motion`; ensure animation is not required to understand a state.
- Keep touch targets comfortably sized and avoid tiny controls in the privacy review flow.
- Preserve text resizing and browser zoom without clipping key actions or privacy details.

## 16. Motion

Use motion sparingly to clarify state changes. Typical transitions are 150–240ms with a gentle ease-out and a small 4–8px movement or fade. Use a restrained fade/slide for panels and message arrival; do not animate every message continuously. Avoid pulsing bubbles, distracting shimmer, or long entrance sequences. Honor `prefers-reduced-motion` by removing nonessential movement.

## 17. Implementation guidance for AI agents

1. Build reusable components for the workspace shell, sidebar, chat message, composer, file chip, privacy summary, finding row, sanitized request preview, and approval actions.
2. Define palette, spacing, radius, shadows, and typography as shared CSS variables or the project's existing token format. Do not scatter one-off hex values through components.
3. Reuse the project's existing framework, icon set, and component conventions. Avoid adding dependencies for visual polish alone.
4. Keep the interface responsive and keyboard-accessible as components are built; do not defer accessibility to a final pass.
5. Use synthetic example data in previews and screenshots. Do not put real credentials, personal information, or document contents into fixtures.
6. Match the visual direction without inventing unsupported product behavior. The UI must reflect the actual analysis, sanitization, approval, and external-provider states.
7. Keep the background solid near-black. Keep liquid-glass materials and the subtle bubble effect in the side panels and selected controls. Preserve a clean central chat.
8. Before finishing a screen, check mobile/tablet/desktop layouts, keyboard focus, text contrast on glass, loading/empty/error states, and that approval clearly names its destination.

### Starter CSS tokens

```css
:root {
  color-scheme: dark;
  --color-background: #07080b;
  --color-background-raised: #0d0f14;
  --color-surface: #15171d;
  --color-glass: rgba(29, 31, 39, 0.78);
  --color-glass-raised: rgba(42, 43, 53, 0.82);
  --color-accent: #b78af7;
  --color-accent-strong: #9d5de8;
  --color-accent-soft: #d7bfff;
  --color-text: #f5f3f8;
  --color-text-secondary: #c8c4d0;
  --color-text-muted: #a29dab;
  --color-border: rgba(230, 225, 240, 0.14);
  --color-border-strong: rgba(230, 225, 240, 0.24);
  --color-success: #83d6a6;
  --color-warning: #f1c875;
  --color-error: #ff7d88;

  --font-sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --space-12: 48px;
  --space-16: 64px;
  --space-24: 96px;

  --radius-sm: 8px;
  --radius-md: 14px;
  --radius-lg: 22px;
  --radius-xl: 28px;
  --radius-pill: 999px;

  --shadow-sm: inset 0 1px 0 rgba(255, 255, 255, 0.035);
  --shadow-md: 0 10px 30px rgba(0, 0, 0, 0.24);
  --shadow-lg: 0 20px 60px rgba(0, 0, 0, 0.32);
}

.glass-panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm), var(--shadow-md);
}

@supports (backdrop-filter: blur(16px)) {
  .glass-panel {
    background: var(--color-glass);
    backdrop-filter: blur(16px) saturate(115%);
  }
}
```
