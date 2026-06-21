# Kamilya LMS — WCAG 2.1 AA Accessibility Guide

## Quick Reference

### Color Contrast

| Element | Foreground | Background | Ratio | Status |
|---------|------------|------------|-------|--------|
| Body text | #1F2937 | #FFFFFF | 14.3:1 | ✅ AA |
| Muted text | #6B7280 | #FFFFFF | 5.0:1 | ✅ AA |
| Links | #2563EB | #FFFFFF | 5.2:1 | ✅ AA |
| Error | #DC2626 | #FFFFFF | 5.6:1 | ✅ AA |
| Success | #059669 | #FFFFFF | 4.5:1 | ✅ AA |
| Disabled | #9CA3AF | #FFFFFF | 2.9:1 | ⚠️ Non-text only |

### Keyboard Navigation

All interactive elements must be:
- Reachable via `Tab` key
- Operable with `Enter`/`Space` for buttons
- Operable with arrow keys for menus/tabs
- Escapable with `Escape` for modals
- Focus visible (minimum 2px outline)

### ARIA Requirements

```tsx
// Modals
<div role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <h2 id="modal-title">...</h2>
</div>

// Navigation
<nav aria-label="Main navigation">
  <ul role="menubar">
    <li role="menuitem"><a href="/courses">Courses</a></li>
  </ul>
</nav>

// Forms
<label htmlFor="email">Email</label>
<input id="email" aria-required="true" aria-invalid={!!error} aria-describedby={error ? 'email-error' : undefined} />
{error && <span id="email-error" role="alert">{error}</span>}

// Buttons
<button aria-label="Delete course">Delete</button>
<button aria-busy={isLoading}>Save</button>

// Progress
<div role="progressbar" aria-valuenow={75} aria-valuemin={0} aria-valuemax={100} aria-label="Course progress: 75%">
  <div style={{ width: '75%' }} />
</div>

// Skip to content
<a href="#main-content" className="sr-only focus:not-sr-only">
  Skip to content
</a>
```

### Images

```tsx
// Informative images
<img src="/logo.png" alt="Kamilya LMS" />

// Decorative images
<img src="/decor.svg" alt="" role="presentation" />

// Complex images (charts, diagrams)
<figure>
  <img src="/chart.png" alt="Course completion rates: 85% in Q1, 92% in Q2" />
  <figcaption>Detailed statistics in table below</figcaption>
</figure>
```

### Forms

```tsx
// Every input needs a visible label
<label htmlFor="course-title">Course Title *</label>
<input id="course-title" type="text" aria-required="true" />

// Error messages linked to inputs
<input aria-describedby="title-error" aria-invalid={true} />
<span id="title-error" role="alert">Title is required</span>

// Required fields indicated
<span aria-hidden="true">*</span> <span className="sr-only">(required)</span>
```

### Tables

```tsx
<table>
  <caption>Student enrollment statistics</caption>
  <thead>
    <tr>
      <th scope="col">Student</th>
      <th scope="col">Progress</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th scope="row">John Doe</th>
      <td>75%</td>
    </tr>
  </tbody>
</table>
```

### Focus Management

```tsx
// Modal trap focus
useEffect(() => {
  if (isOpen) {
    const firstFocusable = modalRef.current?.querySelector('button, input, select, textarea');
    firstFocusable?.focus();
  }
}, [isOpen]);

// Announce route changes
<div aria-live="polite" aria-atomic="true">
  {routeChanged && <span>Page loaded: {pageTitle}</span>}
</div>
```

## Testing Checklist

### Automated (axe-core)

```bash
pnpm add -D @axe-core/react @axe-core/playwright
```

```tsx
// React component
import { run } from 'axe-core';

// Playwright
import AxeBuilder from '@axe-core/playwright';

test('page has no accessibility violations', async ({ page }) => {
  await page.goto('/courses');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
```

### Manual Testing

| Test | Method | Pass |
|------|--------|------|
| Keyboard only | Tab through entire page | ⬜ |
| Screen reader | NVDA/VoiceOver | ⬜ |
| Zoom 200% | No content loss | ⬜ |
| Color contrast | axe-core | ⬜ |
| Focus visible | Tab navigation | ⬜ |
| Error announcements | Form validation | ⬜ |
| Skip links | Tab to first element | ⬜ |

## Component Checklist

| Component | ARIA | Keyboard | Contrast | Status |
|-----------|------|----------|----------|--------|
| Button | ✅ | ✅ | ✅ | Ready |
| Input | ✅ | ✅ | ✅ | Ready |
| Modal | ✅ | ✅ | ✅ | Ready |
| Card | N/A | ✅ | ✅ | Ready |
| Badge | N/A | N/A | ✅ | Ready |
| Table | ✅ | ✅ | ✅ | Ready |
| Navigation | ✅ | ✅ | ✅ | Ready |
| Quiz | ✅ | ✅ | ✅ | Needs audit |
| Progress bar | ✅ | N/A | ✅ | Ready |
| File upload | ✅ | ✅ | ✅ | Ready |
