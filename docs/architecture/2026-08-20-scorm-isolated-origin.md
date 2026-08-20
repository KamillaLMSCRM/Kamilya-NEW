# SCORM 1.2 isolated content origin

Дата: 2026-08-20

## Решение

Tenant-uploaded SCORM HTML/JavaScript не исполняется на origin приложения или
обычного API. API выдаёт learner-у scoped launch token и URL выделенного
cookieless origin из `SCORM_CONTENT_ORIGIN`. В production при пустой настройке
SCORM launch возвращает `503`; остальные функции LMS продолжают работать.

Ожидаемая схема:

```text
https://app.kml.kz
  GET https://api.kml.kz/api/v1/scorm/courses/{course_id}/launch
    -> launch_url=https://scorm.kml.kz/api/v1/scorm/packages/{package_id}/launch?token=...

https://app.kml.kz iframe (sandbox)
  -> https://scorm.kml.kz launch shell
       -> same isolated origin package assets
       -> same isolated origin scoped attempt commit
       -> versioned status-only postMessage to exact app origin
```

## Browser boundary

- Внешний iframe приложения имеет только
  `sandbox="allow-forms allow-same-origin allow-scripts"`, `fullscreen` и
  `referrerPolicy="no-referrer"`; top-navigation, popups, downloads, camera,
  microphone и geolocation не разрешены.
- `allow-same-origin` нужен для совместимости SCORM 1.2 API discovery между
  package frame и launch shell. Это допустимо только потому, что весь runtime
  находится на отдельном origin и не может читать DOM/localStorage приложения.
- Launch shell отправляет наружу только status message версии 1. Приложение
  принимает сообщение лишь при одновременном совпадении `event.origin`,
  `event.source`, случайного `bridge_channel`, типа, версии и allowlist status.
  Сообщение не выполняет серверную mutation и не считается доказательством
  завершения; authoritative completion остаётся в scoped commit API.
- Main API сохраняет `X-Frame-Options: DENY` и `frame-ancestors 'none'`.
  Frameable CSP применяется только к package paths на точном
  `SCORM_CONTENT_ORIGIN` host.

## Обязательный ingress contract

DNS/TLS и reverse proxy для `scorm.kml.kz` должны быть отдельными от app/API
cookie surface. Proxy обязан сохранять исходный `Host` и пропускать только:

- `GET /api/v1/scorm/packages/{package_id}/launch`;
- `GET /api/v1/scorm/packages/{package_id}/assets/...`;
- `GET /api/v1/scorm/packages/{package_id}/assets-token/...`;
- `POST /api/v1/scorm/attempts/{attempt_id}/commit`.

Все остальные пути на SCORM host должны возвращать `404`/`403` на ingress.
Нельзя проксировать туда `/auth`, `/admin`, `/users`, docs/OpenAPI или общий
API prefix. Нельзя задавать cookie с `Domain=.kml.kz`; существующий refresh
cookie остаётся host-only и ограничен `/api/v1/auth`.

Для API runtime:

```text
SCORM_CONTENT_ORIGIN=https://scorm.kml.kz
PUBLIC_URL=https://app.kml.kz
```

## Release gate

До включения SCORM в KZ production:

1. проверить DNS/TLS и точный `Host` на backend;
2. подтвердить, что любой не-SCORM route на `scorm.kml.kz` недоступен;
3. подтвердить на launch response отсутствие `X-Frame-Options`, CSP
   `frame-ancestors https://app.kml.kz`, `Referrer-Policy: no-referrer`;
4. подтвердить, что тот же package launch через `api.kml.kz` возвращает `421`;
5. запустить benign SCORM 1.2 E2E: initialize, set value, commit, resume,
   completion/certificate;
6. запустить synthetic malicious package: попытки читать `window.top.document`,
   app localStorage/cookies, перейти top-level, открыть внешний connect/form и
   подделать bridge channel должны блокироваться;
7. проверить revoke/expiry/enrollment-window и tenant mismatch;
8. сохранить только обезличенные header/status evidence, без launch token и CMI.

Локальные unit/UI tests не заменяют этот production-equivalent browser/ingress
gate. Commit, DNS, proxy, environment и deploy выполняются отдельным release
решением.
