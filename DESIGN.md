# Kamilya LMS — Brand Design System

> **Status:** v1.0 · Living document  
> **Stack:** Next.js 14 · Tailwind CSS v3 · shadcn/ui tokens  
> **Font stack:** Syne (display) · Manrope (body) · DM Mono (code)  
> **Seed palette:** Blue #2563EB · Gold #B8860B · Cream #FAF8F5

---

## 1. Palette

### 1.1 Semantic token map (CSS custom properties)

All color usage must go through these tokens. **Never** reference raw hex (`#2563EB`, `#B8860B`) or Tailwind color names (`blue-600`, `warm-100`, `gold-500`) directly in component code — that is the single largest source of visual drift in this codebase today.

```css
:root {
  /* Backgrounds */
  --background: 36 33% 97%;          /* warm cream #FAF8F5 */
  --foreground: 20 14% 11%;          /* near-black #1A1714 */

  /* Surfaces */
  --card:               0 0% 100%;   /* white */
  --card-foreground:    20 14% 11%;
  --popover:            0 0% 100%;
  --popover-foreground: 20 14% 11%;

  /* Brand primary — blue */
  --primary:            221 83% 53%; /* #2563EB */
  --primary-foreground: 0 0% 100%;
  --primary-light:      221 83% 95%; /* ← add: tinted bg for active states */

  /* Brand accent — gold */
  --accent:             37 67% 51%;  /* #B8860B */
  --accent-foreground:  0 0% 100%;

  /* Neutrals */
  --muted:              36 20% 95%;
  --muted-foreground:   20 7% 46%;
  --secondary:          36 20% 95%;
  --secondary-foreground: 20 14% 11%;

  /* Borders / inputs */
  --border:             36 13% 89%;
  --input:              36 13% 89%;
  --ring:               221 83% 53%;

  /* Destructive */
  --destructive:        0 84% 60%;
  --destructive-foreground: 0 0% 100%;
}
```

### 1.2 Tailwind token aliases

The `tailwind.config.js` maps every CSS var to a semantic utility:

| Utility | Maps to | Use for |
|---------|---------|---------|
| `bg-background` | `hsl(var(--background))` | Page backdrop |
| `bg-card` | `hsl(var(--card))` | Cards, modals, dropdowns |
| `bg-primary` | `hsl(var(--primary))` | Primary buttons, active nav |
| `bg-muted` | `hsl(var(--muted))` | Secondary surfaces, hover fills |
| `bg-accent` | `hsl(var(--accent))` | Gold accents, badges |
| `text-foreground` | `hsl(var(--foreground))` | Body text |
| `text-muted-foreground` | `hsl(var(--muted-foreground))` | Labels, captions, helper text |
| `text-primary` | `hsl(var(--primary))` | Links, active items |
| `text-accent` | `hsl(var(--accent))` | Gold highlights |
| `border-border` | `hsl(var(--border))` | All borders |
| `ring-ring` | `hsl(var(--ring))` | Focus rings |

### 1.3 Raw colour aliases (deprecated — do not expand)

The config also ships legacy `warm-{50..800}` and `gold-{50..700}` scales. These exist because early pages used them before token migration. **New code must not use them.** Existing files (`Sidebar.tsx`, `login/page.tsx`, `demo/page.tsx`) should be refactored to their semantic equivalents:

| Legacy raw | Replace with |
|-----------|-------------|
| `warm-50` | `bg-background` |
| `warm-100` | `bg-muted` |
| `warm-200` | `border-border` |
| `warm-300` | (avoid — use muted-foreground instead) |
| `warm-400` | `text-muted-foreground` |
| `warm-500` | `text-muted-foreground` |
| `warm-600` | `text-muted-foreground` |
| `warm-800` | `text-foreground` |
| `blue-600` | `text-primary` or `bg-primary` |
| `blue-50` | `bg-primary/10` (or extend a `--primary-light` utility) |

### 1.4 Dark mode

The `.dark` block in `globals.css` inverts the same tokens. Use the same semantic utilities — dark mode is automatic via `<html class="dark">` or the `@media (prefers-color-scheme: dark)` override.

---

## 2. Typography

### 2.1 Font roles

| Role | Family | CSS variable | Tailwind utility | Weight range |
|------|--------|-------------|-----------------|-------------|
| Display / wordmark | **Syne** | `--font-syne` | `font-display` | 400, 500, 600, 700, 800 |
| UI body / interface | **Manrope** | `--font-manrope` | `font-sans` | 300–700 |
| Code / numerics | **DM Mono** | `--font-dm-mono` | `font-mono` | 400, 500 |

### 2.2 Font loading — current issue & fix

**Problem:** `layout.tsx` loads four fonts via `next/font/google`:
- `Inter` (assigns `--font-inter`) — **not referenced** in `tailwind.config.js`
- `Manrope` (assigns `--font-manrope`) — correctly wired as `font-sans`
- `Syne` (assigns `--font-syne`) — correctly wired as `font-display`
- `DM Mono` (assigns `--font-dm-mono`) — correctly wired as `font-mono`

The Inter load is an orphaned download: the variable `--font-inter` exists nowhere in `tailwind.config.js` `fontFamily`, and `<body className={manrope.className}>` makes Manrope the page default. Inter produces no visual effect but still ships ~50 KB of glyph data on every page load.

**Fix:** Remove the Inter import and its CSS variable from `layout.tsx`:

```tsx
// layout.tsx — corrected font loading
import { Manrope, Syne, DM_Mono } from "next/font/google";

const manrope = Manrope({ subsets: ["latin", "cyrillic"], variable: "--font-manrope" });
const syne = Syne({ subsets: ["latin"], variable: "--font-syne" });
const dmMono = DM_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-dm-mono" });

export default function RootLayout({ children }) {
  return (
    <html className={`${manrope.variable} ${syne.variable} ${dmMono.variable}`}>
      <body className={manrope.className}>...</body>
    </html>
  );
}
```

If a `--font-inter` fallback is needed for cross-platform rendering (Windows without Manrope), add it to the tailwind config stacks as a last-resort fallback, not as a separate font load:

```js
fontFamily: {
  sans: ['var(--font-manrope)', 'Manrope', 'Inter', ...defaultTheme.fontFamily.sans],
}
```

### 2.3 Type scale

```css
/* Slide / hero (deck mode) */
--text-hero:     clamp(48px, 6vw, 80px);   /* font-display */
--text-h1:       clamp(32px, 4vw, 48px);    /* font-display */
--text-h2:       clamp(24px, 2.5vw, 36px);  /* font-display or font-sans */
--text-h3:       clamp(18px, 1.5vw, 24px);  /* font-sans */

/* UI scale (product) */
--text-lg:       18px;   /* font-sans, leading 7 */
--text-base:     16px;   /* font-sans, leading 6 — body default */
--text-sm:       14px;   /* font-sans, leading 5 */
--text-xs:       12px;   /* font-sans, leading 4 — labels, captions */
--text-2xs:      10px;   /* font-sans uppercase — section headings in nav */

/* Mono */
--text-code:     13px;   /* font-mono — code blocks, numeric badges */
```

### 2.4 Line-height defaults

- Headings: `1.15` (tight) or `1.2`
- Body: `1.6` (keep readable)
- Labels / small: `1.4`
- Code: `1.5`

### 2.5 Letter-spacing

- Display (Syne, sizes ≥ 36px): `-0.02em`
- Body (Manrope, sizes ≤ 16px): `0em`
- Uppercase labels (any font): `0.05em` – `0.08em`
- Mono code: `0em`

---

## 3. Spacing

### 3.1 Layout grid

The product uses a **4px unit grid** (Tailwind default). Key spacing tokens:

| Token | px | rem | Typical use |
|-------|----|-----|-------------|
| `1` | 4 | 0.25 | Inline icon gaps |
| `2` | 8 | 0.5 | Tight element spacing |
| `3` | 12 | 0.75 | Card inner padding (tight) |
| `4` | 16 | 1 | Default card padding, section gap |
| `6` | 24 | 1.5 | Section spacing, form field gap |
| `8` | 32 | 2 | Between major screen sections |
| `10` | 40 | 2.5 | Page padding (mobile) |
| `12` | 48 | 3 | Page padding (desktop) |

### 3.2 Sidebar

- Width: `240px` (expanded), `68px` (collapsed)
- Trigger button: `-right-3 top-20`, 24×24px circle
- Nav item padding: `px-3 py-2.5`, 12px border-radius
- Section heading: `text-[10px] uppercase tracking-wider`, margine `mb-2`

### 3.3 Content max-widths

- Auth forms (login/register): `max-w-md` (448px)
- Demo role picker: `max-w-2xl` (672px)
- Dashboard content: fluid, `max-w-7xl` (1280px) with `px-4 sm:px-6 lg:px-8`

### 3.4 Border radius tokens

| Token | Scale | Components |
|-------|-------|-----------|
| `--radius` | 10px (0.625rem) | Default (cards, dialogs) |
| `rounded-xl` | 12px | Sidebar items, demo cards |
| `rounded-lg` | 8px | Inputs, buttons |
| `rounded-full` | 9999px | Avatars, pill badges |

---

## 4. Motion

### 4.1 Timing curves

All animations use `cubic-bezier(.4,0,.2,1)` — the "standard productive" curve from Material Design 3. This is set globally in `tailwind.config.js`.

```css
--ease-productive: cubic-bezier(.4, 0, .2, 1);
```

### 4.2 Keyframe animations

| Name | Duration | Purpose |
|------|----------|---------|
| `fade-up` | 0.5s | Page entry, section reveal — translateY(16px) → 0 |
| `fade-in` | 0.35s | Micro-interactions, menu items — translateY(6px) → 0 |
| `slide-in` | 0.3s | Sidebar (initial mount) — translateX(-100%) → 0 |

### 4.3 Stagger helpers

Sibling children can opt into staggered entry via `stagger-1` through `stagger-6` classes (defined in `globals.css`), each offset by 50 ms. Use with `animate-fade-up`:

```html
<div class="animate-fade-up stagger-2">...</div>
```

### 4.4 Sidebar collapse

`transition-all duration-300` on the `<aside>` element. Children transition width and padding simultaneously — no custom JS timeline needed.

### 4.5 Cards

- Hover: 0.2s transition on `box-shadow` and `transform`; lift by `translateY(-2px)`
- Shadow tokens: `shadow-card` (base), `shadow-card-hover` (hover), `shadow-card-lg` (modals)

### 4.6 Grain texture

A subtle noise overlay (`grain` class) at `opacity: 0.025` sits above the entire page. It is part of the brand atmosphere and should not be removed or tinted. The class is `grain` (not a layer in the layout component — apply to the outermost wrapper or use the CSS file's fixed pseudo-element).

---

## 5. Voice & tone

### 5.1 Language

The product is bilingual: **Kazakh** (primary), **Russian** (secondary). English is used only for developer-facing strings. All UI labeling, error messages, and empty states are in Kazakh or Russian depending on the user's locale. (Current pages use Russian — `useT()` hook routes to the correct locale.)

### 5.2 Voice principles

1. **Direct, not corporate.** "Введите код" not "Пожалуйста, введите ваш одноразовый код авторизации."
2. **Helpful silence.** Don't explain what just happened unless it failed. No confetti on basic actions.
3. **Error messages own the problem.** "Неверный код" not "Что-то пошло не так."
4. **Consistent button labels.** "Войти", "Зарегистрироваться", "Отправить", "Сохранить" — no synonyms.

### 5.3 Empty states

Every list/table must handle the empty state inline (not a blank page). Pattern:

```tsx
<div className="flex flex-col items-center py-12 text-center">
  <Icon className="w-12 h-12 text-muted-foreground/40 mb-4" />
  <h3 className="text-base font-medium text-foreground">Нет курсов</h3>
  <p className="text-sm text-muted-foreground mt-1">Создайте первый курс, чтобы начать</p>
</div>
```

---

## 6. Anti-patterns & migration checklist

These are design-level issues found in the current codebase. Every new component or page should pass all checks below.

### ❌ text-blue-600 hardcoded (47+ instances)

Raw `text-blue-600`, `bg-blue-600`, `border-blue-200`, `bg-blue-50` appear on the login, register, and demo pages for links, buttons, card backgrounds, and digit-entry boxes.

**Fix:** Replace with semantic tokens:

| Instance | Replace with |
|----------|-------------|
| `bg-blue-600` / `bg-blue-700` | `bg-primary` / `bg-primary/90` or `hover:bg-primary/90` |
| `text-blue-600` (links) | `text-primary` (`hover:underline`) |
| `text-blue-600` (emphasis) | `text-primary` |
| `border-blue-200` | `border-primary/20` |
| `bg-blue-50` | `bg-primary/10` or one-off `bg-primary-light` |
| `from-blue-50 to-white` (gradient bg) | `from-primary/5 to-transparent` or `from-background` |

### ❌ raw warm-* colors in Sidebar

`Sidebar.tsx` uses `warm-100`, `warm-200`, `warm-400`, `warm-500`, `warm-800` directly. These break in dark mode because the warm scale is absolute, not semantic.

**Fix:** Replace per the table in §1.3. For example:

```tsx
// Before
'text-warm-500 hover:bg-warm-100 hover:text-warm-800'
// After
'text-muted-foreground hover:bg-muted hover:text-foreground'
```

```tsx
// Before
'border-r border-warm-200 bg-white'
// After
'border-r border-border bg-card'
```

### ❌ gradient-text hardcodes hex

`globals.css` `.gradient-text` uses raw `#B8860B` and `#2563EB`. These should reference the CSS variables so dark mode can swap them:

```css
.gradient-text {
  background: linear-gradient(135deg, hsl(var(--accent)) 0%, hsl(var(--primary)) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
```

### ❌ No color-mix in generated backgrounds

Several pages use hardcoded tint backgrounds (`bg-blue-50`, `bg-emerald-50`, `bg-violet-50`). Prefer `color-mix()` or `bg-{semantic}/{opacity}`:

```tsx
// Before
className="bg-blue-50 hover:bg-blue-100 border-blue-200"
// After
className="bg-primary/10 hover:bg-primary/15 border-primary/20"
```

### ❌ Inter font loaded but unused

`layout.tsx` downloads Inter via `next/font/google` but never uses it. Remove to save ~50 KB of font payload. If a system sans fallback is desired, add `'Inter'` to the `fontFamily.sans` array in tailwind config — no separate `next/font` load needed.

---

## 7. Logo & brand mark

### 7.1 Current state

The brand mark is a 32×32 SVG with a gold-to-blue diagonal gradient background (`#B8860B` → `#2563EB`) and a white letter "K" in Syne. The wordmark pairs the gradient text "Kamilya" with lighter "LMS".

### 7.2 Component spec — <Logo />

All logo rendering is centralized in `components/brand/Logo.tsx`. Use it everywhere — never inline the SVG.

**Props:**

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `'mark' \| 'full' \| 'wordmark'` | `'full'` | `mark` = icon only; `full` = icon + wordmark; `wordmark` = text only |
| `size` | `number` | `32` | Height of the icon square in px. Wordmark font scales proportionally. |
| `withSubtitle` | `boolean` | `false` | Shows "AI-платформа" below wordmark (sidebar only) |
| `className` | `string` | `''` | Additional wrapper classes |
| `ariaLabel` | `string` | `'Kamilya LMS'` | Accessible label |

**Usage conventions:**

| Location | Variant | Size | withSubtitle |
|----------|---------|------|-------------|
| Sidebar (expanded) | `full` | 32 | `true` |
| Sidebar (collapsed) | `mark` | 32 | `false` |
| Login / Register | `full` | 40 | `false` |
| Demo picker | `full` | 44 | `false` |
| Favicon | `mark` | 32 | `false` |

### 7.3 Favicon — use the Logo component

The current `layout.tsx` inlines an SVG identical to Logo's `mark` variant directly in the `metadata.icons` config. This duplicates the SVG definition and creates a maintenance point whenever the logo changes.

**Fix:** Because Next.js metadata icons must be a URL, import the mark as a data URL or generate it once in a `favicon.ts` utility:

```ts
// app/favicon.ts — generate favicon from brand mark
import { ImageResponse } from 'next/og';

export const size = { width: 32, height: 32 };

export default function Icon() {
  return new ImageResponse(
    (
      <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#B8860B" />
            <stop offset="100%" stopColor="#2563EB" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="6" fill="url(#g)" />
        <text x="16" y="22" fontSize="20" fontWeight="700" fill="white" textAnchor="middle" fontFamily="Syne, sans-serif">K</text>
      </svg>
    ),
    { ...size },
  );
}
```

This keeps the favicon definition in a single file, removes the inline SVG from `layout.tsx`, and allows the Logo component to remain the single source of truth.

### 7.4 Inverse / dark mode

On dark backgrounds or dark mode, the white "K" on gradient remains legible. No separate monochrome variant is needed for now. If a one-color version is required for print or grayscale contexts, use `#2563EB` (primary blue) as the solid fill.

---

## 8. Components

### 8.1 Button

Extended from shadcn/ui. Variants:

| Variant | Class | Background | Text | Use |
|---------|-------|-----------|------|-----|
| Primary | `btn-primary` | `bg-primary` | `text-primary-foreground` | Main CTA |
| Secondary | `btn-secondary` | `bg-secondary` | `text-secondary-foreground` | Alternative action |
| Ghost | `btn-ghost` | transparent | `text-foreground` | Toolbar / nav |
| Outline | `btn-outline` | transparent | `text-foreground` | Border style |
| Destructive | `btn-destructive` | `bg-destructive` | `text-destructive-foreground` | Delete / danger |

Hover: `opacity-90` for filled variants, `bg-muted` for ghost/outline.

### 8.2 Input

Based on shadcn/ui `Input`. Token-driven: `border-input` default border, `ring-ring` focus ring. Height: `h-10` (40px) for default, `h-9` and `h-11` for dense/large.

### 8.3 Card

Used for content grouping (Kanban columns, auth forms, dashboard widgets).

```tsx
<div className="bg-card text-card-foreground rounded-xl border border-border shadow-card p-4 sm:p-6">
```

### 8.4 Sidebar

See §3.2. Defined in `components/layout/Sidebar.tsx`. Must use semantic colors, not raw `warm-*`.

### 8.5 Kanban board

Defined in `globals.css` as `.kanban-col` and `.kanban-card`. The board uses fixed-width columns (280px) with horizontal scroll. Cards use shadow-card with hover elevation.

### 8.6 Command palette

`.cmd-overlay` + `.cmd-box` in globals.css. A blur-backdropped overlay with a card at `12vh` from top. Width: 560px.

### 8.7 Toast

Powered by `@/components/ui/Toast` using a custom `Toaster` component. Variants: success (green), error (red), info (blue). Stacks from bottom-right.

### 8.8 Skip link

`SkipLink` / `SkipToContent` in `components/a11y/`. Must be the first focusable element on every page. Uses the classic "visually hidden until focused" pattern.

---

## 9. Examples

### 9.1 Login page (migrated)

```tsx
// apps/web/src/app/login/page.tsx — after migrating raw blue-* to semantic tokens
<div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-primary/5 to-background">
  <main className="w-full max-w-md p-8 bg-card rounded-xl shadow-card">
    <div className="text-center mb-8">
      <div className="flex justify-center mb-3">
        <Logo variant="full" size={40} />
      </div>
      <h2 className="text-xl font-semibold mt-2">{t('auth.loginWithTelegram')}</h2>
    </div>
    {/* Code digit boxes */}
    <div className="flex justify-center gap-2">
      {code.split('').map((digit, i) => (
        <div key={i}
          className="w-12 h-14 border-2 border-primary/20 rounded-lg flex items-center justify-center text-2xl font-mono font-bold text-primary bg-primary/10"
        >
          {digit}
        </div>
      ))}
    </div>
    {/* Regen link */}
    <button onClick={generateCode}
      className="w-full text-sm text-muted-foreground hover:text-primary underline"
    >
      Получить новый код
    </button>
    {/* Register link */}
    <a href="/register" className="text-primary hover:underline">
      {t('auth.register')}
    </a>
  </main>
</div>
```

### 9.2 Sidebar (migrated)

Key changes from current Sidebar.tsx:

| Current (warm-*) | Migrated (semantic) |
|------------------|-------------------|
| `text-warm-500 hover:bg-warm-100 hover:text-warm-800` | `text-muted-foreground hover:bg-muted hover:text-foreground` |
| `text-warm-400` (section titles) | `text-muted-foreground` |
| `text-warm-800` (user name) | `text-foreground` |
| `text-warm-400` (user role) | `text-muted-foreground` |
| `text-warm-400` (logout) | `text-muted-foreground` |
| `hover:text-red-600` (logout hover) | `hover:text-destructive` |
| `border-warm-200` (sidebar right border) | `border-border` |
| `border-warm-100` (logo divider, user section) | `border-border` |
| `bg-warm-100` (demo back link) | `bg-muted` |

### 9.3 Demo role cards (migrated)

```tsx
// Replace raw blue-50/emerald-50/violet-50 with semantic tints:
const ROLES = [
  {
    role: 'admin',
    color: 'text-primary',
    bg: 'bg-primary/10 hover:bg-primary/15 border-primary/20',
  },
  {
    role: 'teacher',
    color: 'text-emerald-600',  // ← keep secondary semantic once added
    bg: 'bg-emerald-50 hover:bg-emerald-100 border-emerald-200',  // ← migrate when emerald token exists
  },
];
```

**Recommendation:** Add a secondary-status token set (`--success`, `--warning`, `--info`) to support the green/violet role cards without hardcoded Tailwind colors.

### 9.4 Kanban (auth-migrated view)

```tsx
<div className="kanban-col">
  <div className="flex items-center justify-between px-4 py-3 border-b border-border">
    <h3 className="text-sm font-semibold text-foreground">В обработке</h3>
    <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">5</span>
  </div>
  <div className="scroll-inner">
    <div className="kanban-card">
      <p className="text-sm font-medium text-foreground">Курс: Основы Python</p>
      <p className="text-xs text-muted-foreground mt-1">Автор: А. Нурланова</p>
    </div>
  </div>
</div>
```

---

## Migration priority

| Priority | Issue | Files affected | Effort |
|----------|-------|---------------|--------|
| P0 | raw `warm-*` → semantic tokens | `Sidebar.tsx` | 30 min |
| P0 | raw `blue-*` → semantic tokens | `login/page.tsx`, `register/page.tsx`, `demo/page.tsx` | 20 min |
| P0 | Remove orphaned Inter font load | `layout.tsx` | 5 min |
| P1 | `gradient-text` hex → CSS vars | `globals.css` | 2 min |
| P1 | Favicon inline SVG → dedicated `favicon.ts` | `layout.tsx` + new file | 15 min |
| P2 | Role card colors (`emerald-*`, `violet-*`) → semantic tokens | `demo/page.tsx` | 10 min |
| P2 | Add secondary status token set | `globals.css` + `tailwind.config.js` | 15 min |

---

*Generated from codebase audit — `globals.css`, `tailwind.config.js`, `layout.tsx`, `Logo.tsx`, `Sidebar.tsx`, `login/page.tsx`, `register/page.tsx`, `demo/page.tsx`.*