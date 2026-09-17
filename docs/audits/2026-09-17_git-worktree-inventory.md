# Аудит Git worktree и «чужих» изменений

**Дата:** 2026-09-17  
**Репозиторий:** `KamillaLMSCRM/Kamilya-NEW`  
**Режим:** локальная инвентаризация; история и незакоммиченные изменения не удалялись

## Вывод

Признаков работы постороннего разработчика не найдено. HEAD всех обнаруженных
worktree подписан проектным автором `Kamilya Codex <kamilla_lms_crm@proton.me>`.
Повторяющееся сообщение об «unrelated/foreign work» вызывали:

1. основной checkout `C:\Kamilya New\Kamilya-NEW`, оставшийся на старой ветке
   `fix/remove-superadmin-login-link-20260904` с 163 modified/untracked paths;
2. накопленные worktree старых Codex-задач;
3. артефакты проверок и временные ops-скрипты, оставленные незакоммиченными даже
   в уже merged ветках;
4. три экспериментальные чистые ветки, которые не являются предками текущего
   `origin/master` и поэтому не могут быть удалены как завершённые.

Именно поэтому безопасный агент не мог считать основной checkout чистой базой и
каждый раз отдельно предупреждал о чужих для текущей задачи изменениях.

## Что исправлено сейчас

Новая разработка вынесена в чистый worktree:

- path: `C:\Kamilya New\.worktrees\org-hierarchy-v2-20260917`;
- branch: `feature/org-hierarchy-v2-20260917`;
- base: `6205c640fd0b9b6e3bb5a28b89be912915e29e39`;
- незакоммиченные файлы основного checkout туда не переносились.

После отдельной проверки `dirty=false` и `HEAD` является предком
`origin/master` снята регистрация восьми завершённых worktree:

- `course-generation-hardening-20260914`;
- `kamilya-docs-ct137-20260907`;
- `staff-existing-position-20260917`;
- `staff-position-modal-20260917`;
- `_release-053-a507e17b`;
- `ai-cancel-release`;
- `release-0.5.0-clean`;
- `release-0.3.0-worktree`.

Git/Windows не смог физически удалить четыре уже разрегистрированных каталога из-за
слишком длинных имён вложенных файлов:

- `C:\Kamilya New\.worktrees\course-generation-hardening-20260914`;
- `C:\Kamilya New\Kamilya-NEW\.worktrees\release-0.5.0-clean`;
- `C:\Kamilya New\release-0.3.0-worktree`;
- `C:\Kamilya New\.worktrees\org-hierarchy-v2-frontend-20260917`.

Отдельный frontend-agent работал в
`C:\Kamilya New\.worktrees\org-hierarchy-v2-frontend-20260917`. Его commit был
принят в integration-ветку после сравнения одинакового patch-id. Регистрация
worktree и временная branch удалены; физический каталог остался только как
Windows long-path residue и больше не отображается в `git worktree list`.

Они больше не являются Git worktree. Автоматический рекурсивный обход политики
удаления не применялся; остаточные каталоги следует убрать отдельной
контролируемой Windows long-path операцией после повторной проверки точных путей.

Ветки завершённых старых задач не удалялись: снятие worktree не уничтожает Git
history и оставляет возможность аудита. Исключение — временная frontend-ветка
этой задачи, удалённая только после exact patch-id readback и принятия commit в
integration-ветку.

## Что намеренно сохранено

### Dirty, хотя HEAD уже merged

Эти каталоги могут содержать незакоммиченные evidence или код, поэтому не
удалялись:

- `course-confirmation-flow-20260916` — 3 paths;
- `course-role-validation-20260912` — 3 paths;
- `evidence-plan-v2-integration-20260915` — 1 path;
- `legacy-dns-cleanup-20260912` — 30 paths;
- `private-embedding-route-20260912` — 1 path;
- `course-quality-passport-worktree` — 29 paths;
- `course-approval-policy-readback` — 9 paths;
- `crm-release` — 1 path;
- `Kamilya-NEW-release-0.5.54` — 2 paths.

### Не merged в `origin/master`

Даже чистые worktree нельзя считать завершёнными без отдельного review:

- `evidence-plan-engine-20260914` — clean;
- `learning-insights` — clean;
- `learning-insights-frontend-release` — clean;
- `engineering-operating-model-worktree` — 2 dirty paths;
- `Kamilya-NEW-ai-summaries-fix` — 17 dirty paths.

## Правило на будущее

1. Каждая новая задача получает отдельный worktree от свежего `origin/master`.
2. Root-agent не использует основной dirty checkout для реализации или релиза.
3. Перед закрытием задачи агент обязан классифицировать свой worktree:
   committed/pushed/merged либо dirty with owner.
4. Чистый merged worktree удаляется сразу; branch удаляется только после
   независимого remote/readback и при отсутствии recovery value.
5. Dirty worktree не удаляется и не называется «чужой работой»: он получает
   точный owner/status в этом реестре.
6. Главный checkout очищается только отдельной задачей после пофайловой
   классификации 163 paths; reset/clean/broad stash запрещены.
