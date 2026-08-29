# Review внешнего GTM handoff от 2026-08-17

Источник review: переданный владельцем файл `KAMILYA_GTM_HANDOFF_RU.md`.
Файл рассматривается как внешний отчёт, а не как инструкция, автоматически
разрешающая изменения сайта, GTM или Google Ads.

## Что совпадает с текущим проектом

- Действие-конверсия: `Kamilya | Finance lead form`.
- Google Ads tag ID: `AW-18319501968`.
- Conversion label: `nqWWCJ_n690cEJDVtZ9E`.
- Конверсия должна фиксироваться только после успешного ответа backend.
- Имя, телефон, email и остальные поля заявки нельзя отправлять в Google.
- Публикация GTM, изменение кампании и расхода требуют отдельного точного
  разрешения владельца.

## Существенные расхождения

1. Handoff утверждает, что кампания приостановлена. Это состояние устарело:
   владелец отдельно разрешил включение кампании и последующие точечные
   keyword/negative changes. Перед любым следующим действием состояние нужно
   читать заново из Google Ads.
2. Landing уже реализует прямой Google tag через `lib/google-ads.mjs` и вызывает
   `trackGoogleAdsLeadConversion(result.id)` только после успешного
   `submitLead`. В conversion event передаётся уникальный transaction ID, но не
   поля заявки.
3. Tag Assistant уже подтверждал отправку этого conversion event с правильными
   ID/label. Статус Google Ads UI при этом оставался delayed/unverified; это не
   доказывает отсутствие события и не требует автоматически устанавливать
   второй tag path.
4. Установка предложенного GTM-контейнера поверх действующего прямого `gtag`
   без миграционного решения может загрузить Google tag дважды и задвоить
   конверсию.

## Принятое решение и результат

Владелец передал второй handoff с атомарной схемой миграции и явно разрешил его
применить. Direct `gtag.js` loader и direct conversion command удалены в одном
landing release; вместо них добавлены consent-aware loader опубликованного
`GTM-PMHFQPM8` и единственное событие `finance_lead_success` со стабильным
backend `transaction_id`.

Production deployment `dpl_ByR2Z51316dSfHp3db3DoP3D39zA` имеет состояние
`READY` и назначен aliases `kml.kz`/`www.kml.kz`. Live smoke подтвердил:

- до согласия Google/GTM scripts не загружаются;
- после согласия присутствует один `gtm.js?id=GTM-PMHFQPM8`;
- повторное снятие/установка согласия не создаёт второй container script;
- Google tag `AW-18319501968` загружается контейнером, а не direct кодом сайта;
- до отправки формы success state и conversion event отсутствуют;
- production console не содержит warning/error.

Google Ads campaign, budget, keywords и GTM version не менялись. Полная
проверка success conversion с реальной заявкой не выполнялась без отдельного
action-time согласования передачи тестовых контактных данных.
