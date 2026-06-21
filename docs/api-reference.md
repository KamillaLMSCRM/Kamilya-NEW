# Kamilya LMS — API Documentation

## Base URL

```
Production: https://lms.kml.kz/api
Development: http://localhost:8000
```

## Authentication

### JWT Token

All authenticated endpoints require a JWT token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### Token Types

| Type | Duration | Usage |
|------|----------|-------|
| Access token | 30 minutes | API requests |
| Refresh token | 7 days | Token refresh |

---

## Endpoints

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login with email/password |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| POST | `/api/v1/auth/logout` | Logout (invalidate tokens) |

#### Register

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123",
  "first_name": "Иван",
  "last_name": "Иванов",
  "tenant_id": "tenant-uuid"
}
```

**Response:**
```json
{
  "id": "user-uuid",
  "email": "user@example.com",
  "first_name": "Иван",
  "last_name": "Иванов",
  "role": "student",
  "created_at": "2026-06-21T10:00:00Z"
}
```

#### Login

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

---

### Courses

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/courses/` | List courses |
| POST | `/api/v1/courses/` | Create course |
| GET | `/api/v1/courses/{id}` | Get course |
| PUT | `/api/v1/courses/{id}` | Update course |
| DELETE | `/api/v1/courses/{id}` | Delete course |
| POST | `/api/v1/courses/{id}/publish` | Publish course |
| POST | `/api/v1/courses/{id}/unpublish` | Unpublish course |
| POST | `/api/v1/courses/{id}/duplicate` | Duplicate course |

#### Create Course

```http
POST /api/v1/courses/
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "Основы маркетинга",
  "description": "Курс для начинающих маркетологов",
  "language": "ru"
}
```

**Response:**
```json
{
  "id": "course-uuid",
  "title": "Основы маркетинга",
  "description": "Курс для начинающих маркетологов",
  "language": "ru",
  "status": "draft",
  "tenant_id": "tenant-uuid",
  "created_at": "2026-06-21T10:00:00Z"
}
```

---

### Modules & Lessons

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/courses/{course_id}/structure` | Get course structure |
| POST | `/api/v1/courses/{course_id}/modules` | Create module |
| PUT | `/api/v1/modules/{id}` | Update module |
| DELETE | `/api/v1/modules/{id}` | Delete module |
| POST | `/api/v1/modules/{id}/lessons` | Create lesson |
| PUT | `/api/v1/lessons/{id}` | Update lesson |
| DELETE | `/api/v1/lessons/{id}` | Delete lesson |
| POST | `/api/v1/courses/{id}/reorder` | Reorder structure |

#### Create Module

```http
POST /api/v1/courses/{course_id}/modules
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "Модуль 1: Введение",
  "order": 1
}
```

#### Create Lesson

```http
POST /api/v1/modules/{module_id}/lessons
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "Урок 1.1: Что такое маркетинг",
  "order": 1,
  "content": {
    "blocks": [
      {
        "type": "text",
        "content": "Маркетинг — это..."
      }
    ]
  }
}
```

---

### Enrollments

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/enrollments/` | List enrollments |
| POST | `/api/v1/enrollments/` | Enroll student |
| DELETE | `/api/v1/enrollments/{id}` | Unenroll student |

#### Enroll Student

```http
POST /api/v1/enrollments/
Authorization: Bearer <token>
Content-Type: application/json

{
  "user_id": "user-uuid",
  "course_id": "course-uuid"
}
```

---

### Progress

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/progress/` | Get course progress |
| POST | `/api/v1/progress/` | Update lesson progress |
| GET | `/api/v1/progress/course/{id}` | Get detailed course progress |

#### Update Progress

```http
POST /api/v1/progress/
Authorization: Bearer <token>
Content-Type: application/json

{
  "lesson_id": "lesson-uuid",
  "status": "completed",
  "time_spent": 300
}
```

---

### Quizzes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/quizzes/{id}` | Get quiz |
| POST | `/api/v1/quizzes/{id}/submit` | Submit quiz answers |

#### Submit Quiz

```http
POST /api/v1/quizzes/{quiz_id}/submit
Authorization: Bearer <token>
Content-Type: application/json

{
  "answers": [
    {
      "question_id": "question-uuid",
      "selected_choice_id": "choice-uuid"
    }
  ]
}
```

**Response:**
```json
{
  "score": 85,
  "passed": true,
  "correct_answers": 4,
  "total_questions": 5,
  "feedback": [
    {
      "question_id": "question-uuid",
      "correct": true,
      "explanation": "Правильный ответ"
    }
  ]
}
```

---

### Certificates

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/certificates/` | List certificates |
| POST | `/api/v1/certificates/{id}/issue` | Issue certificate |
| GET | `/api/v1/certificates/{id}/verify` | Verify certificate |

#### Issue Certificate

```http
POST /api/v1/certificates/{enrollment_id}/issue
Authorization: Bearer <token>
```

**Response:**
```json
{
  "id": "certificate-uuid",
  "number": "KML-2026-000001",
  "course_id": "course-uuid",
  "user_id": "user-uuid",
  "issued_at": "2026-06-21T10:00:00Z",
  "expires_at": "2027-06-21T10:00:00Z"
}
```

#### Verify Certificate

```http
GET /api/v1/certificates/{number}/verify
```

**Response:**
```json
{
  "valid": true,
  "number": "KML-2026-000001",
  "course_title": "Основы маркетинга",
  "user_name": "Иван Иванов",
  "issued_at": "2026-06-21T10:00:00Z",
  "expires_at": "2027-06-21T10:00:00Z"
}
```

---

### Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/documents/` | List documents |
| POST | `/api/v1/documents/upload` | Upload document |
| DELETE | `/api/v1/documents/{id}` | Delete document |

#### Upload Document

```http
POST /api/v1/documents/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: [binary]
description: "Учебный материал"
```

---

### AI Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/ai/generate` | Start course generation |
| GET | `/api/v1/ai/status/{job_id}` | Check generation status |
| WS | `/api/v1/ai/ws/{job_id}` | WebSocket progress updates |

#### Start Generation

```http
POST /api/v1/ai/generate
Authorization: Bearer <token>
Content-Type: application/json

{
  "document_ids": ["doc-uuid-1", "doc-uuid-2"],
  "target_audience": "Начинающие маркетологи",
  "num_modules": 5,
  "language": "ru"
}
```

**Response:**
```json
{
  "job_id": "job-uuid",
  "status": "queued",
  "message": "Курс генерируется..."
}
```

#### Check Status

```http
GET /api/v1/ai/status/{job_id}
Authorization: Bearer <token>
```

**Response:**
```json
{
  "job_id": "job-uuid",
  "status": "completed",
  "progress": 100,
  "course_id": "course-uuid",
  "message": "Курс успешно создан"
}
```

---

### Student

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/student/dashboard` | Get student dashboard |
| GET | `/api/v1/student/courses` | List enrolled courses |
| GET | `/api/v1/student/courses/{id}` | Get course progress |

#### Get Dashboard

```http
GET /api/v1/student/dashboard
Authorization: Bearer <token>
```

**Response:**
```json
{
  "enrolled_courses": 5,
  "completed_courses": 2,
  "in_progress_courses": 3,
  "certificates": 2,
  "recent_activity": [
    {
      "course_id": "course-uuid",
      "course_title": "Основы маркетинга",
      "progress": 75,
      "last_activity": "2026-06-21T10:00:00Z"
    }
  ]
}
```

---

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/admin/stats` | Get dashboard statistics |
| GET | `/api/v1/admin/users` | List all users |
| GET | `/api/v1/admin/courses` | List all courses |
| GET | `/api/v1/admin/enrollments` | List all enrollments |
| GET | `/api/v1/admin/export/users` | Export users CSV |
| GET | `/api/v1/admin/export/courses` | Export courses CSV |
| GET | `/api/v1/admin/export/enrollments` | Export enrollments CSV |
| GET | `/api/v1/admin/export/quiz-results` | Export quiz results CSV |

#### Get Statistics

```http
GET /api/v1/admin/stats
Authorization: Bearer <token>
```

**Response:**
```json
{
  "total_users": 150,
  "active_users": 120,
  "total_courses": 25,
  "published_courses": 20,
  "enrollments": 500,
  "completed_enrollments": 300,
  "certificates": 280,
  "ai_generated_courses": 15
}
```

---

### Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/users/` | List users |
| POST | `/api/v1/users/` | Create user |
| GET | `/api/v1/users/{id}` | Get user |
| PUT | `/api/v1/users/{id}` | Update user |
| DELETE | `/api/v1/users/{id}` | Delete user |
| POST | `/api/v1/users/{id}/block` | Block user |
| POST | `/api/v1/users/{id}/unblock` | Unblock user |

---

## Error Responses

### Validation Error

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Authentication Error

```json
{
  "detail": "Could not validate credentials"
}
```

### Authorization Error

```json
{
  "detail": "Not enough permissions"
}
```

### Not Found

```json
{
  "detail": "Resource not found"
}
```

---

## Rate Limiting

API endpoints are rate-limited:

| Endpoint | Limit |
|----------|-------|
| `/api/v1/auth/login` | 5 requests/minute |
| `/api/v1/auth/register` | 3 requests/minute |
| Other endpoints | 60 requests/minute |

When rate limited, response:
```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```
