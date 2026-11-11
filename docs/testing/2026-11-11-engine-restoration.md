# Восстановление наработок движка — 11 ноября 2026

Задача: восстановить полезное поведение, потерянное при переходе на simple,
проверить сохранённые дефекты, затем три полных курса в DEV. Это текущий
локальный отчёт, **не разрешение считать candidate92 принятым**.

| Наработка | Что потерялось | Что восстановлено и как проверено |
|---|---|---|
| Независимость решения вопроса | Card-review получал авторский ключ и объяснение, мог заимствовать скрытый контекст | Старый `practical_option_predicates`: только видимый заголовок теста, вопрос и отдельный вариант; ключ/объяснение/урок скрыты. Отдельный review объяснений. Реальный RED payload-leak → 49 focused PASS, включая five-stage owned transport и cold replay |
| Адресная правка с сохранением хорошего | Editor мог переписать несвязанный вопрос вместе с телом урока | Серверное объединение по domain/target; остальные поля и изображения сохранены. Сохранённый PDF: одна незапрошенная правка отброшена |
| Сохранение незакрытых замечаний | Молчание editor могло погасить вопрос или потерять material finding без поля lesson | Явный source-question decision, UNVERIFIED для молчания; неподдержанный scope сохранён как ordinary editorial issue. Не выдаётся за неоднозначность исходника |
| Источник отдельно от курса | Проверка всего курса могла засчитать правильный тест как объяснение в уроке | Возвращено прежнее source→prose задание, без тестов; PDF prevention-duty найден и исправлен без подсказки target |
| Текущая согласованная редакция отдельно от истории | Заменённое слово попадало в нормативный контекст | Текущий текст и все approved reasons; заменённые quote/offset остаются в аудите, не передаются как действующая норма |
| Источник примера формы | Кассовый образец был превращён в универсальную обязанность бухгалтера | Blind generic guide НЕ помог: отрицательный контроль сохранён и guide убран. Один editor по зарегистрированному QA замечанию исправил курс; это addressed repair, не blind discovery |

Новый путь содержит пять содержательных ролей: author → source/prose review →
independent option reader → explanation review → scoped editor. Старые каскады
полностью не возвращаются. Смена модели, ослабление source/custody gates или
новые регулярки для финансовых формулировок не применялись.

## Сохранённые контроли

Все ниже — local component, источник неизменён, business writes=0, Luna6/HIGH.
Авторская стадия заменена сохранённым курсом. Старый ответ используется только
при точном совпадении request bytes и response SHA; cached tokens не новый расход.

| Контроль | Свежие обращения, input/output | Итог |
|---|---|---|
| H5 PDF, прежний prose-review + scoped editor | 3; 134323/13543 | Independent local GO: предотвращение конфликта восстановлено; 8L24Q. Не native DEV |
| H5 cash, самостоятельное обнаружение | 3; 110718/11745 | FAIL: обязанность из образца осталась |
| H5 standards, прежний card-review | 3; 58107/7614 | FAIL: location в l3q2 снова пропущен. Именно это привело к проверке утечки ключа |
| H6 cash, guide о примерах | 2; 78646/10379, card exact-cache | FAIL; guide удалён. Повторять настройку общего лозунга нельзя |
| H7 cash, supplied QA finding → editor | 1; 38616/7435, card exact-cache, supplied prose-review | Independent local GO: убрана неподтверждённая обязанность, 8L28Q/10markers, ключи и остальные процедуры сохранены. Не blind discovery |
| H8 standards, восстановленный key-blind reader + explanation reviewer | 3; 68530/11184, prose exact-cache 18538/1841 | Independent full4L15Q local GO, изменён только l3q2stem. Ошибку обнаружил explanation reviewer; blind reader сам location miss не заметил |

Evidence roots: `.release-evidence/simple-course-restoration-20261111` (H5),
`simple-course-restoration-examples-20261111` (H6),
`simple-course-restoration-addressed-20261111` (H7),
`simple-course-restoration-blind-20261111` (H8).

Технически: текущая полная suite **7977 PASS/1skip/7warnings/91.74s**;
focused72 PASS/3.00s, включая gate6, baseline1004/2174 PASS. Независимый source
review подтвердил consumer L92F: quiet UNDECIDABLE теперь actionable ordinary
issue. Exact five-stage owned/cold replay проверен без inference. Source graph
refresh после freeze выполняется отдельно.
Все результаты с датой и границей сохраняются; старый FAIL не переписывается.

DEV остаётся91/b71b89f6; production90/16504ca0 и frontend86 не менялись в этой
работе. Три ранее завершённых DEV91 курса не были semantic GO и не заменяют
три будущих fresh native курса candidate92. Денежная стоимость managed Luna
не предоставлена сервисом, UNKNOWN; токены считаются фактические.
