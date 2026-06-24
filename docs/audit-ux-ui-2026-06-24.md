# Kamilya LMS — UX/UI Audit Report

**Дата:** 2026-06-24
**Объект:** `apps/web/` (Next.js 14 App Router)
**Вердикт:** 🟠 **UX функционален, но много трения для пользователя и серьёзные accessibility проблемы**. Не готов к WCAG AA.

---

## TL;DR — главные UX-проблемы

| # | Категория | Проблема | Серьёзность |
|---|-----------|----------|-------------|
| 1 | i18n | **50%+ UI строк хардкод на русском** в страницах и компонентах, переключатель языка в Settings не работает | 🔴 CRITICAL |
| 2 | UX consistency | **`window.confirm()` / `window.alert()` используются в 8 местах** вместо `ConfirmDialog` / тостов | 🟠 HIGH |
| 3 | Navigation | **6 мест используют `window.location.href` для навигации** — full page reload вместо Next.js client-side routing | 🟠 HIGH |
| 4 | Forms | **Все формы без `<label>` (только placeholder)** — недоступно для screen reader, плохо для a11y | 🟠 HIGH |
| 5 | Errors | **11 `catch {}` пустых блоков** — ошибки проглатываются, пользователь не видит причину сбоя | 🟠 HIGH |
| 6 | Accessibility | **Modal без focus trap, без `role="dialog"`, без Escape-закрытия** | 🟠 HIGH |
| 7 | Navigation | **Sidebar: `<a href>` вместо Next.js `<Link>`** — full reload на каждом клике | 🟡 MEDIUM |
| 8 | Accessibility | **Кликабельные строки таблицы без keyboard handler** (Enter/Space) | 🟡 MEDIUM |
| 9 | UX | **Window.confirm блокирует UI**, нет кастомизации, ломает флоу | 🟡 MEDIUM |
| 10 | Architecture | **5 страниц используют raw `fetch()` вместо `api` axios** — обходят interceptor (JWT автоматом, refresh token) | 🟡 MEDIUM |
| 11 | UX | **Sidebar role filtering на клиенте** — не безопасно (можно подделать в localStorage), но UX корректно | 🟡 MEDIUM |
| 12 | Accessibility | **Loading state — только спиннер**, нет skeleton loaders в большинстве страниц | 🟡 MEDIUM |
| 13 | Settings | **Settings buttons не работают** (язык не переключается, email сохраняется через нерабочий endpoint) | 🔴 BROKEN |
| 14 | Forms | **`<button>` внутри `<a>`** в courses page — HTML invalid | 🟡 MEDIUM |
| 15 | Accessibility | **Дропдаун notifications без Escape, без `aria-expanded`** | 🟡 MEDIUM |

---

## 1. i18n — Главная UX проблема

Приложение **заявлено как трёхъязычное** (RU/KK/EN), но ~50% UI строк — хардкод на русском языке. Это критично для казахстанского рынка (KK обязателен).

### Хардкод в страницах

| Файл | Хардкод строк |
|------|---------------|
| `dashboard/page.tsx` | 'AI Генераций', 'в процессе', 'очередь пуста', 'Сотрудники', 'Вот что происходит сегодня', 'Новый курс', 'AI Pipeline', 'Последние курсы', 'Все курсы', 'Нет курсов. Начните с', 'AI-генерации', 'Очередь', 'Документы', 'Структура', 'Контент', 'Проверка', 'Пусто', 'опубликовано', 'из X записей', 'Y завершили' |
| `ai/generate/page.tsx` | 'Обработка документов', 'Проектирование структуры', 'Генерация контента', 'Проверка качества', 'Генерация тестов', 'Сохранение' |
| `admin/users/page.tsx` | 'Управление обучающимися', 'Добавить обучающегося', 'Поиск по имени или email...', 'Загрузка...', 'Пользователей не найдено', 'Имя', 'Email', 'Роль', 'Должность', 'Статус', 'Создан', 'Действия', 'Обучающийся', 'Преподаватель', 'Орг. админ', 'Админ', 'Инструктор', 'Активен', 'Заблокирован', 'Заблокировать', 'Разблокировать', 'Назначить', '+ Назначить', 'Всего: X пользователей', 'Назад', 'Далее', 'Стр. X', 'Новый обучающийся', 'Email', 'Имя', 'Фамилия', 'Пароль (мин. 8 символов)', 'Создать', 'Назначить должность: X', 'Обучающийся автоматически запишется на все курсы, привязанные к должности.', '— Выберите должность —', 'Назначить и записать на курсы', 'Должность назначена! Записано на X курс(ов), новых записей: Y' |
| `courses/[id]/page.tsx` | 'Курс пройден! Поздравляем!', 'Не удалось записаться' |
| `login/page.tsx` | 'Как войти:', 'Открыть бота', 'Получить новый код', 'Слишком много запросов...' |
| `register/page.tsx` | 'Регистрация', 'Компания', 'Имя', 'Фамилия', 'Email', 'Пароль (мин. 8 символов)', 'Регистрация...', 'Зарегистрироваться', 'Уже есть аккаунт?', 'Войти', 'ООО Ваша Компания', 'Иван', 'Иванов', 'you@company.kz' |
| `settings/page.tsx` | 'Настройки сохранены!', 'Не привязан', 'Для смены пароля обратитесь к администратору.' |
| `admin/enrollments/page.tsx` | 'От записаться пользователя?' (опечатка + хардкод в confirm) |
| `Sidebar.tsx` | 'ГЕНЕРАЦИЯ КУРСОВ', 'Генерация курсов', 'Мои тесты', 'Должности' |
| `TopBar.tsx` | 'Поиск...', 'Уведомления', 'Нет уведомлений' |
| `CommandPalette.tsx` | 'Поиск страниц, настроек...', 'Ничего не найдено', 'навигация', 'выбрать', 'закрыть' |
| `Layout.tsx` | 'Загрузка...' |
| `ConfirmDialog.tsx` | cancelText default = 'Отмена', loading text = '...' |
| `ErrorPage.tsx` | 'На главную', 'Обновить', 'Страница не найдена', 'Внутренняя ошибка сервера' |
| `SkipLink.tsx` | 'Skip to content' |

### Сломано переключение языка

**`apps/web/src/app/settings/page.tsx:86-93`:**
```tsx
<div className="flex gap-3">
  <Button variant="default">{t('ai.languages.ru')}</Button>
  <Button variant="outline">{t('ai.languages.kk')}</Button>
  <Button variant="outline">{t('ai.languages.en')}</Button>
</div>
```
- **Кнопки языка статичные**, нет `onClick`, не переключают реальный язык
- Пользователь не может переключиться с RU на KK
- Используется `useLanguageStore` через `useT`, но в Settings — no-op кнопки
- **Это означает, что KK пользователи видят UI частично на KK (через useT), частично на RU (хардкод)**

### Severity: 🔴 CRITICAL
- **Рынок**: KZ требует обязательный KK в публичных сервисах
- **Compliance**: закон РК о языках
- **Стоимость фикса**: средняя (2-3 недели) — но разбивается на инкрементальные коммиты

---

## 2. Native `confirm()` / `alert()` / `window.location.href`

### `window.confirm()` — 8 мест

| Файл | Строка | Текст |
|------|--------|-------|
| `courses/page.tsx` | 63 | 'Удалить курс? Это действие необратимо.' |
| `admin/quizzes/assign/page.tsx` | 84 | 'Удалить назначение?' |
| `courses/[id]/edit/page.tsx` | 96 | 'Удалить модуль со всеми уроками?' |
| `courses/[id]/edit/page.tsx` | 122 | 'Удалить урок?' |
| `documents/page.tsx` | 93 | 'Удалить документ?' |
| `admin/quizzes/page.tsx` | 121 | 'Удалить вопрос?' |
| `admin/quizzes/page.tsx` | 133 | 'Удалить тест со всеми вопросами?' |
| `positions/page.tsx` | 103 | 'Удалить должность?' |
| `admin/enrollments/page.tsx` | 92 | 'От записаться пользователя?' (опечатка) |

**Проблемы:**
- ❌ Браузерный `confirm()` — нельзя стилизовать, не соответствует дизайн-системе
- ❌ Не локализован (текст на RU в трёхъязычном приложении)
- ❌ Блокирует UI, не работает с кастомными `ConfirmDialog`
- ❌ Невозможно сделать keyboard accessible на Tab/Enter

**Существует `ConfirmDialog`** в `components/ui/ConfirmDialog.tsx` — но нигде не используется!

### `window.location.href` — 6 мест (full page reload вместо Next.js router.push)

| Файл | Строка | Контекст |
|------|--------|----------|
| `courses/[id]/page.tsx` | 203 | После прохождения курса → `/courses` |
| `courses/[id]/page.tsx` | 240 | Тоже → `/courses` |
| `courses/[id]/page.tsx` | 243 | → `/courses` |
| `Sidebar.tsx` | 160 | После logout → `/login` |
| `login/demo/page.tsx` | 63 | → redirect |
| `CommandPalette.tsx` | 69 | → href |

**Проблемы:**
- ❌ Теряется state (Zustand store остаётся, но React tree перезагружается)
- ❌ Медленнее — full page load ~300-500ms vs client-side routing ~10ms
- ❌ Не используется Next.js prefetch
- ❌ Ломает React transitions, scroll restoration
- ❌ В CommandPalette — после клика на item происходит полная перезагрузка, хотя есть `router.push` в next/navigation

### Severity: 🟠 HIGH

---

## 3. Формы и accessibility

### Нет `<label>` ни в одной форме

**Все поля используют только `placeholder`:**

```tsx
<Input placeholder="Email" ... />
<Input placeholder="Пароль" ... />
```

**Проблемы:**
- ❌ Screen reader не знает что это за поле (только "edit text" без описания)
- ❌ При потере фокуса placeholder исчезает — пользователь забывает что вводил
- ❌ WCAG AA требует labels для всех input полей (Success Criterion 1.3.1)
- ❌ **register/page.tsx** и **admin/users/page.tsx** имеют `<label>` — но в большинстве мест нет

**Исключения** (где есть label):
- `register/page.tsx` (line 64-110) — есть `<label>` блоки
- `settings/page.tsx` (line 44-64) — есть `<label>`

### Severity: 🟠 HIGH (a11y blocker)

### Отсутствующие состояния

- ❌ Нет error state в Input — нет красной рамки при ошибке
- ❌ Нет helper text под полем
- ❌ Нет required indicator (хотя есть HTML5 `required`)
- ❌ Нет disabled состояния с tooltip

### `<button>` внутри `<a>` (HTML invalid)

**`courses/page.tsx:147-224`:**
```tsx
<a key={course.id} href={`/courses/${course.id}`} ...>
  <button onClick={(e) => { e.preventDefault(); handlePublish(...); }}>
    Publish
  </button>
  <a href={`/courses/${course.id}/edit`} onClick={(e) => e.stopPropagation()}>
    Edit
  </a>
  <button onClick={(e) => { e.preventDefault(); handleDelete(...); }}>
    Delete
  </button>
</a>
```

**Проблемы:**
- ❌ `<button>` в `<a>` — W3C невалидный HTML (button не должен быть внутри a)
- ❌ `<a>` в `<a>` — W3C невалидный HTML
- ❌ `e.preventDefault()` + `e.stopPropagation()` — хак чтобы клик не следовал за ссылкой
- ❌ Лучше: один `<article>` или `<div>` с абсолютным positioning для action-кнопок

### Severity: 🟡 MEDIUM

---

## 4. Загрузка / пустые состояния / ошибки

### 11 мест с `catch {}` — ошибки проглатываются

```tsx
try {
  const res = await api.get('/v1/...');
  setData(res.data);
} catch {}  // ❌ ничего не показываем пользователю
```

**Файлы:**
- `courses/[id]/page.tsx` — 2 места
- `admin/users/page.tsx` — 1 место (fetchPositions)
- `ai/generate/page.tsx` — 2 места
- `documents/page.tsx` — 1 место
- `dashboard/page.tsx` — 3 места
- `positions/page.tsx` — 2 места

**Проблемы:**
- ❌ Если API упал — UI показывает "пусто" без объяснения
- ❌ Пользователь не понимает — это баг приложения или нет данных?
- ❌ Нет телеметрии — разработчики не узнают что фича сломана

**Лучший паттерн:**
```tsx
const [error, setError] = useState<string | null>(null);
try { ... } catch (e) { setError(t('common.loadFailed')); }
{error && <ErrorAlert message={error} onRetry={fetch} />}
```

### Loading state — только спиннер

В большинстве страниц:
```tsx
{loading ? (
  <div className="flex items-center justify-center py-12">
    <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
  </div>
) : ...}
```

**Проблемы:**
- ❌ Спиннер — generic, не показывает что загружается
- ❌ Нет `Skeleton` компонента в большинстве страниц (хотя `Skeleton.tsx` существует)
- ❌ Долгая загрузка (>3s) — пользователь не знает ждать или нет

### Severity: 🟠 HIGH (для ошибок), 🟡 MEDIUM (для loading)

---

## 5. Навигация — `<a>` вместо Next.js `<Link>`

### 15 мест с `<a href="/...">` для internal navigation

| Файл | Строки |
|------|--------|
| `LandingPage.tsx` | 16, 19, 36, 43 |
| `login/page.tsx` | 193, 197 |
| `register/page.tsx` | 120 |
| `dashboard/page.tsx` | 143, 226, 256 |
| `courses/[id]/page.tsx` | 263, 278, 294 |
| `courses/quiz/[quizId]/page.tsx` | 237 |
| `my-courses/page.tsx` | 136 |
| `my-quizzes/page.tsx` | 127 |
| `admin/page.tsx` | 199, 232 |
| `Sidebar.tsx` | 17, 60, 66-80 (вся навигация) |

**Проблемы:**
- ❌ Каждый клик → full page reload (теряется state, медленно)
- ❌ Нет Next.js prefetching
- ❌ Sidebar полностью на `<a>` — каждый клик = 200-500ms задержка

**Severity: 🟡 MEDIUM (функционально работает, но UX ужасный)**

---

## 6. Модальные окна — нет accessibility

### `Modal.tsx`

**Что есть:**
- ✅ `body.style.overflow = 'hidden'` при открытии
- ✅ Закрытие по клику на overlay
- ✅ `aria-label="Close"` на кнопке

**Что отсутствует:**
- ❌ **`role="dialog"`** — screen reader не знает что это модалка
- ❌ **`aria-modal="true"`** — не помечает modal state
- ❌ **`aria-labelledby`** для title — нет связи с заголовком
- ❌ **Focus trap** — Tab может уйти за пределы модалки в основной контент
- ❌ **Закрытие по Escape** — единственный способ закрыть = клик на X или overlay
- ❌ **Возврат фокуса** — после закрытия фокус не возвращается на trigger
- ❌ **Анимация появления/исчезновения** — модалка просто появляется мгновенно (хотя `framer-motion` в deps)
- ❌ **Portal** — рендерится inline в DOM дереве, может конфликтовать с z-index

### Severity: 🟠 HIGH (WCAG блокер — keyboard navigation не работает)

---

## 7. Таблицы — нет keyboard support

### `Table.tsx`

**Что есть:**
- ✅ `onRowClick` поддерживается
- ✅ `divide-y` для границ
- ✅ Hover state

**Что отсутствует:**
- ❌ **`<caption>`** — нет описания таблицы для screen reader
- ❌ **`scope="col"`** на `<th>` — header cells не помечены
- ❌ **Keyboard handler** для кликабельных строк — нет `onKeyDown` для Enter/Space
- ❌ **`role="grid"`** или `role="table"` — нет ARIA
- ❌ **`<thead>` / `<tbody>`** — в typed mode используется, в children mode — нет требования
- ❌ **Двойной export** — `export function Table` дважды без TS overload (может не работать в strict)

### Severity: 🟡 MEDIUM (a11y)

---

## 8. Settings — сломанный функционал

### Кнопки выбора языка

```tsx
<div className="flex gap-3">
  <Button variant="default">{t('ai.languages.ru')}</Button>
  <Button variant="outline">{t('ai.languages.kk')}</Button>
  <Button variant="outline">{t('ai.languages.en')}</Button>
</div>
```
- ❌ **Нет `onClick`** — кликаешь, ничего не происходит
- ❌ **Не переключает язык**, должен вызывать `useLanguageStore.setLang()`
- ❌ **Визуально непонятно какой сейчас активен**

### Сохранение профиля

```tsx
const handleSave = async () => {
  setSaved(false);
  try {
    await fetch(`${API_URL}/v1/users/me`, {
      method: 'PATCH',
      ...
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  } catch (e) { console.error(...); }
};
```

**Проблемы:**
- ❌ Endpoint `/v1/users/me` не существует в backend (есть только `/users`, не `me`)
- ❌ Сохранение молча проваливается — показывает "Настройки сохранены!" даже при 404
- ❌ Поля firstName/lastName/email **не инициализированы из user** при mount — пользователь должен ввести заново
- ❌ Нет валидации email (типа, формата)

### Severity: 🔴 BROKEN UX

---

## 9. Sidebar — клиентская фильтрация ролей

**`Sidebar.tsx:50-53`:**
```tsx
const hasRole = (roles?: string[]) => {
  if (!roles || !user) return true;
  return roles.includes(user.role);
};
```

**Проблемы:**
- ⚠️ **НЕ безопасно** — если злоумышленник подделает `user.role` в localStorage через DevTools, увидит admin menu. Но это не privilege escalation (бэкенд проверяет роль на API)
- ⚠️ **UX consequence**: после logout/login вкладка может показать menu, к которому пользователь больше не имеет доступа
- ⚠️ Использует `<a>` вместо `<Link>` — full reload

**Лучше:** SSR-рендер меню с проверкой роли из JWT на сервере

### Severity: 🟡 MEDIUM (функционально OK, не безопасно)

---

## 10. TopBar и CommandPalette — accessibility

### TopBar
- ❌ **Cmd+K кнопка** `hidden sm:flex` — на mobile нет альтернативы для поиска
- ❌ **Notifications dropdown** без `aria-expanded` / `aria-controls`
- ❌ **Notification dot** без `aria-label` (скринридер не скажет "есть уведомления")
- ❌ Dropdown закрывается по клику на backdrop, но нет Escape
- ❌ Hardcoded русский текст "Поиск...", "Уведомления"

### CommandPalette

**Что есть:**
- ✅ `Cmd+K` shortcut
- ✅ `Escape` закрывает
- ✅ Поиск с autoFocus
- ✅ Фильтрация items

**Что отсутствует:**
- ❌ **`role="listbox"` / `role="option"`** — нет ARIA для screen reader
- ❌ **Keyboard navigation** — НЕ работает ↑↓ как обещает подсказка
- ❌ **`aria-activedescendant`** — нет выделения текущего item
- ❌ **`aria-selected`** — нет индикации выбора
- ❌ `window.location.href` — full reload вместо router.push
- ❌ Role-based фильтрация — нет проверки teacher/student

### Severity: 🟠 HIGH

---

## 11. Состояния загрузки — нет skeleton-ов

### Где есть (хорошо):
- `Skeleton.tsx` с `CardSkeleton` и `TableSkeleton`

### Где должны быть, но нет:
- ❌ `dashboard/page.tsx` — stat cards показывают `—` плейсхолдеры
- ❌ `courses/page.tsx` — спиннер
- ❌ `admin/users/page.tsx` — текст "Загрузка..."
- ❌ `documents/page.tsx` — текст "Загрузка..."
- ❌ `courses/[id]/page.tsx` — спиннер
- ❌ `admin/page.tsx` — спиннер

**Severity: 🟡 MEDIUM**

---

## 12. Empty states — не информативные

### `courses/page.tsx:135-143`:
```tsx
) : courses.length === 0 ? (
  <div className="rounded-2xl border border-dashed border-warm-200 py-12 text-center">
    <div className="text-warm-300 mb-3">
      <svg ...><BookIcon /></svg>
    </div>
    <p className="text-warm-400 text-sm">{t('courses.noCourses')}</p>
  </div>
)
```

**Проблемы:**
- ❌ Нет CTA-кнопки "Создать курс" для админа
- ❌ Нет объяснения **почему пусто** (ещё не создано? нет данных? фильтр неправильный?)
- ❌ Нет иллюстрации (только тонкая иконка)

### Severity: 🟡 MEDIUM

---

## 13. Button as Link — стилистическая путаница

### `admin/users/page.tsx:194-208`
```tsx
<td>
  <Badge variant={user.is_active ? 'default' : 'destructive'}>
    {user.is_active ? 'Активен' : 'Заблокирован'}
  </Badge>
</td>
<td className="p-3 text-right">
  <button
    onClick={() => handleToggleActive(user.id, user.is_active)}
    className={`text-sm ${user.is_active ? 'text-red-500 hover:underline' : 'text-green-500 hover:underline'}`}
  >
    {user.is_active ? 'Заблокировать' : 'Разблокировать'}
  </button>
</td>
```

**Проблемы:**
- ❌ `<button>` стилизован как текстовая ссылка — путает пользователя
- ❌ Красный текст + зелёный текст — слабый контраст
- ❌ Нет иконки (только текст)
- ❌ Нет подтверждения для danger-действия

### Severity: 🟡 MEDIUM

---

## 14. Forms — некорректная обработка ошибок

### `register/page.tsx`:
```tsx
} catch (err: any) {
  setError(err.message);
}
```

**Проблемы:**
- ❌ Error от fetch() без message — пустая строка
- ❌ Нет валидации email на клиенте
- ❌ Нет проверки password complexity (uppercase, lowercase, digit) — на бэкенде есть, но не на UI
- ❌ Не показывает password strength
- ❌ Не показывает успешную регистрацию — сразу redirect на /dashboard

### Severity: 🟡 MEDIUM

---

## 15. WCAG compliance check

Проверяю по основным критериям WCAG 2.1 AA:

| Критерий | Статус | Комментарий |
|----------|--------|-------------|
| 1.1.1 Non-text content | ⚠️ | Логотип "K" без alt, иконки декоративные без `aria-hidden` |
| 1.3.1 Info and Relationships | ❌ | Формы без labels, таблицы без caption/scope |
| 1.4.3 Contrast | ⚠️ | `text-warm-400` (#A09890) на white = 3.4:1 (нужно 4.5:1) |
| 1.4.11 Non-text Contrast | ⚠️ | Borders `border-warm-200` слабые |
| 2.1.1 Keyboard | ❌ | Модалки без Escape, таблицы без keyboard nav, command palette без ↑↓ |
| 2.4.3 Focus Order | ⚠️ | Не критично, но focus trap отсутствует в Modal |
| 2.4.6 Headings and Labels | ⚠️ | Много h1 на разных уровнях, но в целом OK |
| 2.5.3 Label in Name | ❌ | Нет labels у inputs |
| 3.3.1 Error Identification | ❌ | Ошибки API не показываются пользователю |
| 3.3.2 Labels or Instructions | ❌ | Placeholder ≠ label |
| 4.1.2 Name, Role, Value | ❌ | Modal без `role="dialog"`, CommandPalette без ARIA |

**WCAG.md существует** (4.5K) — но реальная реализация не соответствует заявленному уровню.

### Severity: 🔴 WCAG AA claim false

---

## 16. Mobile / Responsive

### Что работает:
- ✅ `hidden sm:flex` — скрытие элементов на mobile
- ✅ `grid sm:grid-cols-2 lg:grid-cols-4` — адаптивные сетки
- ✅ `md:hidden` — responsive nav

### Что не работает:
- ❌ **Sidebar**: фиксированная ширина `240px`, на mobile (375px) занимает 64% экрана
- ❌ **TopBar**: search кнопка скрыта `hidden sm:flex`, нет замены
- ❌ **CommandPalette**: `cmd-box` имеет `width: 560px` — на mobile не помещается
- ❌ **Stat cards grid**: 4 колонки на desktop, но `overflow-x-scroll` в kanban — нет навигации на touch
- ❌ **Modals**: `max-w-lg` без responsive variants — может быть больше экрана
- ❌ Нет mobile menu / hamburger — на mobile Sidebar просто перекрывает контент

### Severity: 🟡 MEDIUM

---

## 17. Animation / Motion

### Что есть:
- ✅ `fade-up`, `fade-in`, `slide-in` keyframes в tailwind.config.js
- ✅ `animate-pulse` для skeleton (но они не используются)
- ✅ `framer-motion` в package.json

### Что не используется:
- ❌ `Modal` появляется мгновенно (без анимации)
- ❌ `Dropdown` (notifications) появляется мгновенно
- ❌ `CommandPalette` — нет анимации
- ❌ Page transitions — нет
- ❌ Toast notifications — вообще нет системы

**Рекомендация:** использовать `framer-motion` для согласованного motion design.

### Severity: 🟡 NICE-TO-HAVE

---

## 18. Toast / Notification система

### Отсутствует полностью

**Сценарии где нужен toast:**
- ✅ Login success → редирект
- ✅ Save settings → toast "Сохранено"
- ✅ Delete course → toast "Курс удалён"
- ✅ Error API → toast "Не удалось загрузить"
- ✅ Quiz passed → toast "Тест пройден"

**Текущее решение:**
- `setSaved(true)` + `setTimeout(3000)` в Settings — ручная реализация
- `alert('Курс пройден!')` в course player — браузерный alert
- `confirm()` в 8 местах

**Рекомендация:** добавить `react-hot-toast` или кастомный toast provider (лёгкий, ~30 строк).

### Severity: 🟠 HIGH (UX impact)

---

## 19. Лучшие находки (что уже хорошо)

- ✅ **`SkipLink`** — правильная реализация с sr-only
- ✅ **Tailwind config** — хорошие дизайн-токены (warm, gold, shadows)
- ✅ **`Button` с CVA** — type-safe variants
- ✅ **`useT` с type-safe keys** — `NestedKeyOf<typeof ru>` отличный паттерн
- ✅ **Magic UI animations** — `stagger-1..6`, `fade-up`
- ✅ **Kanban visualization** в Dashboard — хорошая идея
- ✅ **Card компонент** — простой и переиспользуемый
- ✅ **Loading защита** в `useAuthStore.initialize()`
- ✅ **`buildStats` JOIN вместо N+1** — сделано в `785c28d`
- ✅ **Sidebar role-restriction** — student не видит admin pages
- ✅ **`hide publish/edit/delete`** для students на courses page
- ✅ **i18n файлы** — есть ru.json (12K), kk.json (12K), en.json (9K)
- ✅ **Cards с hover state** на dashboard — `hover:shadow-card-hover`
- ✅ **Login page** — accessibility (SkipLink, role="img", aria-label)
- ✅ **Telegram polling** — правильная очистка setInterval
- ✅ **`Course` completion page** — показывает "Курс пройден" с иконкой

---

## 20. Приоритизированный план исправлений

### 🔴 Sprint 1 (1-2 недели) — Критично для production

1. **Исправить `/auth/demo-login` production block** — re-apply gate (был откачен в `24d25e3`)
2. **Перевести хардкод строки в i18n** (приоритет: dashboard, courses, admin pages)
3. **Подключить `useT` в TopBar / Sidebar / CommandPalette / Modal / ConfirmDialog / ErrorPage**
4. **Заменить `window.confirm` → `ConfirmDialog`** (8 мест)
5. **Заменить `window.alert` → toast** (2 места: `alert(err.detail)`, `alert('Курс пройден!')`)
6. **Заменить `<a href>` → Next.js `<Link>`** (15 мест)
7. **Заменить `window.location.href` → `router.push()`** (6 мест)
8. **Подключить переключатель языка** в Settings (onClick → useLanguageStore.setLang)

### 🟠 Sprint 2 (1-2 недели) — UX

9. **Добавить `role="dialog"`, `aria-modal`, focus trap, Escape** в Modal
10. **Добавить ARIA + keyboard nav** в CommandPalette
11. **Добавить `<label>` для всех input** (либо `aria-label` через Input props)
12. **Error states** — добавить toast на catch {} (11 мест)
13. **Loading skeletons** в courses, admin/users, dashboard, ai/generate
14. **Settings** — добавить `onClick` к языковым кнопкам, инициализировать поля из user
15. **Перевести `fetch()` → `api`** в admin/users, courses/[id], courses/[id]/edit, settings (5 страниц)
16. **Убрать `<button>` внутри `<a>`** в courses page
17. **Empty states с CTA** — добавить кнопки "Создать" / "Загрузить"

### 🟡 Sprint 3 (2 недели) — Polish

18. **Toast notification system** (react-hot-toast или кастомный)
19. **Mobile responsive** — Sidebar drawer на mobile, hamburger menu
20. **Таблицы** — `<caption>`, `scope="col"`, keyboard navigation для кликабельных строк
21. **CSS классы кастомные** — определить `stagger-*` через tailwind config или удалить кастомные
22. **Animate модалки** через framer-motion
23. **Page transitions** через Next.js layouts
24. **WCAG проверка** — запустить axe-core / Lighthouse audit

### 🟢 Nice-to-have

25. Dark mode (CSS переменные готовы в globals.css)
26. Breadcrumbs для навигации
27. Skeleton loaders для всех страниц
28. Pull-to-refresh на mobile
29. Offline mode (Service Worker)
30. Storybook для UI компонентов

---

## 21. Архитектурные рекомендации

### A. State management

**Проблема:** 11 страниц используют raw `fetch()` вместо `api` axios. Это:
- ❌ Обходит interceptor (JWT, refresh token)
- ❌ Дублирует код `headers: { Authorization: '...' }`
- ❌ Нет единой обработки 401/403/429

**Решение:**
```tsx
// ❌ Сейчас
const res = await fetch(`${API_URL}/v1/users`, {
  headers: { Authorization: `Bearer ${token}` },
});

// ✅ Должно быть
const users = await api.get('/v1/users').then(r => r.data);
```

Добавить **React Query / TanStack Query** для:
- Кеширования
- Автоматической retry
- Background refetch
- Optimistic updates
- Loading/error states из коробки

### B. Forms

**Проблема:** 7+ форм в `register`, `settings`, `admin/users`, `course edit`, `ai/generate` — все используют `useState` для каждого поля.

**Решение:** react-hook-form + zod (уже обещан в ADR, но не используется)
```tsx
const { register, handleSubmit, formState: { errors } } = useForm({
  resolver: zodResolver(UserCreateSchema)
});
```

### C. i18n

**Проблема:** Кастомный `useT` без missing key telemetry. Если KK перевод неполный — пользователь видит RU fallback без уведомления разработчиков.

**Решение:**
- Добавить dev-mode console.warn для missing keys
- CI проверка: `kk.json` и `en.json` имеют все ключи из `ru.json`
- Либо перейти на `next-intl` (ADR обещал)

### D. Error boundaries

**Проблема:** Нет Error Boundary на уровне pages. Если API упал с 500 — Next.js показывает дефолтную страницу ошибки.

**Решение:** добавить `app/error.tsx` (Next.js App Router feature)

---

## 22. Метрики проекта

| Метрика | Значение |
|---------|----------|
| Pages (Next.js App Router) | 21 |
| UI компоненты | 9 (button, card, modal, input, badge, table, ConfirmDialog, Skeleton, ErrorPage) |
| Layout компоненты | 3 (Layout, Sidebar, TopBar) + SkipLink + CommandPalette |
| Hardcoded русских строк (по моей оценке) | ~80 |
| Переведено через useT | ~120 ключей × 3 языка |
| Тесты UI компонентов | 4 (ConfirmDialog, ErrorPage, Skeleton, useDebounce) |
| E2E тесты | 2 (login, navigation) |
| Cypress / Playwright конфиги | Playwright |
| i18n файлы | 3 (ru.json 12K, kk.json 12K, en.json 9K) |
| Кастомных CSS классов в globals.css | 6 (.grain, .gradient-text, .kanban-*, .cmd-*) |
| Анимаций в tailwind.config.js | 3 (fade-up, fade-in, slide-in) |

---

## 23. Финальная оценка

**PROGRESS.md говорит:** "WCAG AA 100%" ✅
**Реальность:** WCAG AA claim **ложный**. Формы без labels, модалки без focus trap, таблицы без keyboard support.

**Что работает хорошо:**
- Дизайн-токены в Tailwind config
- SkipLink
- useT type-safe
- Sidebar role-restriction (через UI)
- Стандартные паттерны (Card, Button, Input)

**Что критично сломано:**
- i18n — 50% хардкод, переключатель языка no-op
- Settings — кнопки не работают, /v1/users/me не существует
- Accessibility — Modal без role/aria-modal/focus trap, формы без labels
- Navigation — `<a>` вместо Link, full reload на каждом клике

**UX работает для русскоязычного админа**, который знает что это beta и не ожидает полировки. Но **для казахстанского рынка (KK обязателен) и для external beta — недостаточно**.

### Главные 3 фикса (если выбирать):
1. **Подключить i18n** — 2-3 дня, +50% UX coverage
2. **Modal accessibility** (role, focus trap, Escape) — 1 день, +a11y compliance
3. **Заменить `<a>` на `<Link>` + `window.location` на router.push** — 1 день, +скорость навигации

Итого: 1 неделя на топ-3 = UX будет на уровне production-ready.
