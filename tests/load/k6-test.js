// Kamilya LMS load testing entrypoint.
//
// Run examples:
//   k6 run tests/load/k6-test.js
//   BASE_URL=https://kamilya-lms-api.onrender.com SCENARIO=learners VUS=100 DURATION=10m k6 run tests/load/k6-test.js
//   BASE_URL=https://kamilya-lms-api.onrender.com AUTH_TOKEN=... COURSE_ID=... LESSON_IDS=a,b,c QUIZ_IDS=x,y k6 run tests/load/k6-test.js
//
// The default profile is intentionally read/progress oriented. AI generation,
// staff import, and write-heavy admin flows must be enabled explicitly because
// they create data, spend LLM budget, and can affect a real tenant.

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const API_PREFIX = __ENV.API_PREFIX || '/api/v1';
const SCENARIO = __ENV.SCENARIO || 'mixed';
const VUS = Number(__ENV.VUS || 50);
const DURATION = __ENV.DURATION || '5m';
const RAMP_TARGET = Number(__ENV.RAMP_TARGET || 500);
const RAMP_HOLD = __ENV.RAMP_HOLD || '10m';

const AUTH_TOKEN = __ENV.AUTH_TOKEN || '';
const ADMIN_AUTH_TOKEN = __ENV.ADMIN_AUTH_TOKEN || '';
const METHODOLOGIST_AUTH_TOKEN = __ENV.METHODOLOGIST_AUTH_TOKEN || '';
const LOGIN_EMAIL = __ENV.LOGIN_EMAIL || '';
const LOGIN_PASSWORD = __ENV.LOGIN_PASSWORD || '';
const USER_CSV = __ENV.USER_CSV || '';

const COURSE_ID = __ENV.COURSE_ID || '';
const LESSON_IDS = csv(__ENV.LESSON_IDS);
const QUIZ_IDS = csv(__ENV.QUIZ_IDS);
const ENABLE_WRITES = (__ENV.ENABLE_WRITES || 'false') === 'true';
const ENABLE_AI = (__ENV.ENABLE_AI || 'false') === 'true';
const ENABLE_IMPORT = (__ENV.ENABLE_IMPORT || 'false') === 'true';
const STAFF_FILE = __ENV.STAFF_FILE || '';

export const errorRate = new Rate('kamilya_errors');
export const authFailures = new Counter('kamilya_auth_failures');
export const aiJobsStarted = new Counter('kamilya_ai_jobs_started');
export const loginDuration = new Trend('kamilya_login_duration');
export const lessonProgressDuration = new Trend('kamilya_lesson_progress_duration');
export const courseStructureDuration = new Trend('kamilya_course_structure_duration');
export const quizSubmitDuration = new Trend('kamilya_quiz_submit_duration');

let cachedToken = '';

const users = new SharedArray('users', () => {
  if (!USER_CSV) return [];
  return open(USER_CSV)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [email, password, token] = line.split(',').map((part) => part.trim());
      return { email, password, token };
    });
});

export const options = buildOptions();

function buildOptions() {
  const thresholds = {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<1500', 'p(99)<4000'],
    kamilya_errors: ['rate<0.02'],
    kamilya_login_duration: ['p(95)<1500'],
    kamilya_lesson_progress_duration: ['p(95)<1200'],
    kamilya_course_structure_duration: ['p(95)<1500'],
    kamilya_quiz_submit_duration: ['p(95)<2000'],
  };

  if (SCENARIO === 'ramp500') {
    return {
      scenarios: {
        ramp500: {
          executor: 'ramping-vus',
          startVUs: 0,
          stages: [
            { duration: '3m', target: 100 },
            { duration: '5m', target: 250 },
            { duration: '5m', target: RAMP_TARGET },
            { duration: RAMP_HOLD, target: RAMP_TARGET },
            { duration: '3m', target: 0 },
          ],
          exec: 'mixed',
        },
      },
      thresholds,
    };
  }

  const execByScenario = {
    learners: 'learners',
    admins: 'admins',
    ai: 'aiGeneration',
    import: 'staffImport',
    mixed: 'mixed',
  };

  return {
    scenarios: {
      [SCENARIO]: {
        executor: 'constant-vus',
        vus: VUS,
        duration: DURATION,
        exec: execByScenario[SCENARIO] || 'mixed',
      },
    },
    thresholds,
  };
}

export function setup() {
  console.log(`Kamilya LMS load test: ${BASE_URL}${API_PREFIX}`);
  console.log(`scenario=${SCENARIO} vus=${VUS} duration=${DURATION}`);
  if (!AUTH_TOKEN && !LOGIN_EMAIL && users.length === 0) {
    console.warn('No AUTH_TOKEN, LOGIN_EMAIL, or USER_CSV provided. Requests will fail with 401.');
  }
  if (!COURSE_ID) console.warn('COURSE_ID is not set; course-detail flow will be skipped.');
  if (LESSON_IDS.length === 0) console.warn('LESSON_IDS is empty; lesson progress flow will be skipped.');
  if (QUIZ_IDS.length === 0) console.warn('QUIZ_IDS is empty; quiz submit flow will be skipped.');
  return { startedAt: Date.now() };
}

export function teardown(data) {
  console.log(`Load test finished in ${Math.round((Date.now() - data.startedAt) / 1000)}s`);
}

export function mixed() {
  const n = (__VU + __ITER) % 100;
  if (n < 80) return learners();
  if (n < 95) return admins();
  if (n < 98) return staffImport();
  return aiGeneration();
}

export function learners() {
  const headers = authHeaders();
  if (!headers) return;

  group('learner dashboard and course reading', () => {
    get('/student/dashboard', headers, [200]);
    get('/courses?status=published&per_page=20', headers, [200]);
    if (COURSE_ID) {
      const structure = timedGet('/courses/' + COURSE_ID + '/structure', headers, courseStructureDuration);
      checkResponse(structure, 'course structure', [200, 404]);
    }
  });

  if (COURSE_ID) {
    group('course progress', () => {
      get('/progress/courses/' + COURSE_ID, headers, [200, 404]);
      get('/progress/courses/' + COURSE_ID + '/completed-ids', headers, [200, 404]);
    });
  }

  if (LESSON_IDS.length > 0) {
    group('lesson progress save', () => {
      const lessonId = pick(LESSON_IDS);
      const res = timedRequest(
        'PUT',
        '/progress/lessons/' + lessonId,
        JSON.stringify({ completed: true }),
        headers,
        lessonProgressDuration,
      );
      checkResponse(res, 'lesson progress saved', [200, 404]);
      get('/quizzes/by-lesson/' + lessonId, headers, [200, 404]);
    });
  }

  if (QUIZ_IDS.length > 0) {
    group('quiz read and optional submit', () => {
      const quizId = pick(QUIZ_IDS);
      const quiz = get('/quizzes/' + quizId, headers, [200, 404]);
      if (ENABLE_WRITES && quiz.status === 200) {
        const body = buildQuizSubmission(quiz.json());
        const submit = timedRequest(
          'POST',
          '/quizzes/' + quizId + '/submit',
          JSON.stringify(body),
          headers,
          quizSubmitDuration,
        );
        checkResponse(submit, 'quiz submitted', [200, 400, 404]);
      }
    });
  }

  sleep(randomBetween(1, 4));
}

export function admins() {
  const headers = authHeaders(true, ADMIN_AUTH_TOKEN || AUTH_TOKEN);
  if (!headers) return;

  group('admin overview', () => {
    get('/admin/stats', headers, [200, 403]);
    get('/admin/trial-usage', headers, [200, 403, 404]);
    get('/users?per_page=50', headers, [200, 403]);
    get('/admin/staff/apply-rules/status/probe-' + __VU, headers, [200, 403]);
    get('/quizzes/grouped', headers, [200, 403]);
  });

  if (ENABLE_WRITES) {
    group('admin safe write probe', () => {
      const suffix = `${Date.now()}-${__VU}-${__ITER}`;
      const payload = {
        personnel_number: `lt-${suffix}`,
        first_name: 'Load',
        last_name: 'Probe',
        department: 'Load Testing',
        position: 'Temporary Probe',
        email: `load-probe-${suffix}@example.invalid`,
        phone: null,
      };
      const res = post('/admin/staff/manual', payload, headers, [201, 403, 409, 429]);
      if (res.status === 201) {
        console.warn('Created staff probe row. Use a dedicated load-test tenant for write tests.');
      }
    });
  }

  sleep(randomBetween(2, 5));
}

export function staffImport() {
  if (!ENABLE_IMPORT) {
    sleep(1);
    return;
  }
  const headers = authHeaders(false, METHODOLOGIST_AUTH_TOKEN || ADMIN_AUTH_TOKEN || AUTH_TOKEN);
  if (!headers || !STAFF_FILE) return;

  group('staff import preview', () => {
    const fileBytes = open(STAFF_FILE, 'b');
    const payload = {
      file: http.file(fileBytes, STAFF_FILE.split(/[\\/]/).pop() || 'staff.xlsx'),
      mapping: '',
      sheet_name: '',
    };
    const res = http.post(url('/admin/staff/import/preview'), payload, { headers });
    checkResponse(res, 'staff import preview', [200, 400, 403, 413, 422]);
  });

  sleep(randomBetween(5, 15));
}

export function aiGeneration() {
  if (!ENABLE_AI) {
    sleep(1);
    return;
  }
  const headers = authHeaders(true, METHODOLOGIST_AUTH_TOKEN || ADMIN_AUTH_TOKEN || AUTH_TOKEN);
  if (!headers) return;

  group('ai generation start and poll', () => {
    const body = {
      documents: csv(__ENV.AI_DOCUMENT_IDS),
      target_audience: __ENV.AI_TARGET_AUDIENCE || 'Нагрузочный тест: методолог проверяет очередь генерации.',
      num_modules: Number(__ENV.AI_NUM_MODULES || 1),
      language: __ENV.AI_LANGUAGE || 'ru',
      course_id: __ENV.AI_COURSE_ID || null,
    };
    if (body.documents.length === 0) {
      console.warn('AI_DOCUMENT_IDS is empty; AI generation request may fail validation.');
    }
    const res = post('/ai/generate-course', body, headers, [202, 400, 403, 429, 502]);
    if (res.status === 202) {
      aiJobsStarted.add(1);
      const jobId = res.json('id');
      if (jobId) get('/ai/jobs/' + jobId, headers, [200, 404]);
    }
  });

  sleep(randomBetween(10, 30));
}

function authHeaders(contentType = true, preferredToken = '') {
  const token = preferredToken || resolveToken();
  if (!token) {
    authFailures.add(1);
    errorRate.add(1);
    sleep(1);
    return null;
  }
  const headers = { Authorization: `Bearer ${token}` };
  if (contentType) headers['Content-Type'] = 'application/json';
  return headers;
}

function resolveToken() {
  if (AUTH_TOKEN) return AUTH_TOKEN;
  if (cachedToken) return cachedToken;
  if (users.length > 0) {
    const user = users[(__VU - 1) % users.length];
    if (user.token) return user.token;
    if (user.email && user.password) {
      cachedToken = login(user.email, user.password);
      return cachedToken;
    }
  }
  if (LOGIN_EMAIL && LOGIN_PASSWORD) {
    cachedToken = login(LOGIN_EMAIL, LOGIN_PASSWORD);
    return cachedToken;
  }
  return '';
}

function login(email, password) {
  const res = http.post(
    url('/auth/login'),
    JSON.stringify({ email, password }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  loginDuration.add(res.timings.duration);
  checkResponse(res, 'login', [200]);
  if (res.status !== 200) {
    authFailures.add(1);
    return '';
  }
  return res.json('access_token') || '';
}

function get(path, headers, okStatuses) {
  const res = http.get(url(path), { headers });
  checkResponse(res, path, okStatuses);
  return res;
}

function timedGet(path, headers, trend) {
  const res = http.get(url(path), { headers });
  trend.add(res.timings.duration);
  return res;
}

function post(path, payload, headers, okStatuses) {
  const res = http.post(url(path), JSON.stringify(payload), { headers });
  checkResponse(res, path, okStatuses);
  return res;
}

function timedRequest(method, path, body, headers, trend) {
  const res = http.request(method, url(path), body, { headers });
  trend.add(res.timings.duration);
  return res;
}

function checkResponse(res, name, okStatuses) {
  const ok = check(res, {
    [`${name}: expected status`]: (r) => okStatuses.includes(r.status),
  });
  if (!ok) {
    errorRate.add(1);
    console.warn(`${name}: status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  } else {
    errorRate.add(0);
  }
  return ok;
}

function buildQuizSubmission(quiz) {
  const questions = Array.isArray(quiz.questions) ? quiz.questions : [];
  return {
    answers: questions.map((question) => ({
      question_id: question.id,
      selected_choice_ids: question.choices && question.choices[0] ? [question.choices[0].id] : [],
    })),
    time_spent_seconds: randomBetween(20, 180),
  };
}

function url(path) {
  return `${BASE_URL}${API_PREFIX}${path.startsWith('/') ? path : `/${path}`}`;
}

function csv(value) {
  return (value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function randomBetween(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}
