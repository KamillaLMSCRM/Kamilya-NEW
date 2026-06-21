// Kamilya LMS — k6 Load Testing

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const loginDuration = new Trend('login_duration');
const courseListDuration = new Trend('course_list_duration');

// Configuration
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const USERNAME = __ENV.USERNAME || 'test@kamilya.kz';
const PASSWORD = __ENV.PASSWORD || 'testpass123';

// Test scenarios
export const options = {
  scenarios: {
    // Constant load test
    constant_load: {
      executor: 'constant-vus',
      vus: 50,
      duration: '5m',
      exec: 'constantLoad',
    },
    // Ramp-up test
    ramp_up: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 100 },
        { duration: '5m', target: 100 },
        { duration: '2m', target: 200 },
        { duration: '5m', target: 200 },
        { duration: '2m', target: 0 },
      ],
      exec: 'rampUp',
    },
    // Stress test
    stress: {
      executor: 'constant-vus',
      vus: 500,
      duration: '10m',
      exec: 'stressTest',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<2500'], // P95 < 2.5s
    errors: ['rate<0.1'], // Error rate < 10%
    login_duration: ['p(95)<2000'],
    course_list_duration: ['p(95)<1500'],
  },
};

// Helper: login and get token
function login() {
  const res = http.post(`${BASE_URL}/api/v1/auth/login`, JSON.stringify({
    email: USERNAME,
    password: PASSWORD,
  }), {
    headers: { 'Content-Type': 'application/json' },
  });

  check(res, {
    'login successful': (r) => r.status === 200,
  });

  if (res.status !== 200) {
    errorRate.add(1);
    return null;
  }

  return res.json('access_token');
}

// Scenario: Constant load
export function constantLoad() {
  const token = login();
  if (!token) return;

  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  // List courses
  const coursesRes = http.get(`${BASE_URL}/api/v1/courses/`, { headers });
  check(coursesRes, {
    'courses list success': (r) => r.status === 200,
  });
  courseListDuration.add(coursesRes.timings.duration);

  sleep(2);

  // Get profile
  const profileRes = http.get(`${BASE_URL}/api/v1/auth/me`, { headers });
  check(profileRes, {
    'profile success': (r) => r.status === 200,
  });

  sleep(1);
}

// Scenario: Ramp-up
export function rampUp() {
  const token = login();
  if (!token) return;

  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  // List courses
  const coursesRes = http.get(`${BASE_URL}/api/v1/courses/`, { headers });
  check(coursesRes, {
    'courses list success': (r) => r.status === 200,
  });

  sleep(1);

  // Create course (write operation)
  const createRes = http.post(`${BASE_URL}/api/v1/courses/`, JSON.stringify({
    title: `Load Test Course ${Date.now()}`,
    description: 'Performance testing course',
  }), { headers });

  check(createRes, {
    'course created': (r) => r.status === 201,
  });

  sleep(2);
}

// Scenario: Stress test
export function stressTest() {
  const token = login();
  if (!token) return;

  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  // Multiple rapid requests
  const batch = http.batch([
    { method: 'GET', url: `${BASE_URL}/api/v1/courses/`, headers },
    { method: 'GET', url: `${BASE_URL}/api/v1/enrollments/`, headers },
    { method: 'GET', url: `${BASE_URL}/api/v1/certificates/`, headers },
  ]);

  batch.forEach((res) => {
    check(res, {
      'batch request success': (r) => r.status === 200,
    });
  });

  sleep(0.5);
}

// Setup: runs once before test
export function setup() {
  console.log(`Running load tests against: ${BASE_URL}`);
  return { startTime: Date.now() };
}

// Teardown: runs once after test
export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Test completed in ${duration}s`);
}
