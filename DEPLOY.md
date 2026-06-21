# Kamilya LMS — Production Deployment Guide

## Prerequisites

- Ubuntu 22.04+ VPS
- Docker & Docker Compose
- Domain: `lms.kml.kz`
- SSL certificate (Let's Encrypt or Cloudflare Origin)

## Quick Deploy

```bash
# 1. Clone repository
git clone https://github.com/KamillaLMSCRM/Kamilya-NEW.git
cd Kamilya-NEW

# 2. Create .env file
cp .env.example .env
# Edit .env with production values

# 3. Start services
docker compose -f docker-compose.prod.yml up -d

# 4. Run migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# 5. Create admin user
docker compose -f docker-compose.prod.yml exec api python -c "
from app.core.db import get_session
from app.modules.users.service import create_user
import asyncio

async def main():
    async with get_session() as db:
        await create_user(
            db=db,
            tenant_id='your-tenant-id',
            email='admin@kml.kz',
            first_name='Admin',
            last_name='User',
            role='superadmin',
            password='your-secure-password',
        )
        await db.commit()

asyncio.run(main())
"
```

## Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/kamilya

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET=your-super-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=30

# CORS
CORS_ORIGINS=["https://app.kml.kz","https://web-acvn10y1u-kamillalmscrms-projects.vercel.app"]

# AI (Qwen)
QWEN_CHAT_URL=http://10.66.66.7:8555/v1
QWEN_EMBEDDINGS_URL=http://10.66.66.7:8001/v1

# Storage
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

## Docker Compose (Production)

```yaml
version: '3.8'

services:
  api:
    build: ./apps/api
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - JWT_SECRET=${JWT_SECRET}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  web:
    build: ./apps/web
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=https://lms.kml.kz/api
    restart: unless-stopped

  worker:
    build: ./apps/api
    command: celery -A app.core.celery_app worker -l info
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  postgres:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=kamilya
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/prod.conf:/etc/nginx/nginx.conf
      - ./nginx/ssl:/etc/nginx/ssl
    depends_on:
      - api
      - web
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

## Nginx Configuration

```nginx
upstream api_backend {
    server api:8000;
}

upstream web_frontend {
    server web:3000;
}

server {
    listen 80;
    server_name lms.kml.kz;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name lms.kml.kz;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    # Security headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # API
    location /api/ {
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /api/v1/ai/ws/ {
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # Frontend
    location / {
        proxy_pass http://web_frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Health Checks

```bash
# API health
curl https://lms.kml.kz/api/health

# Frontend
curl https://lms.kml.kz/

# Database
docker compose exec postgres pg_isready
```

## Monitoring

```bash
# View logs
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f web

# Check status
docker compose ps

# Restart services
docker compose restart api worker web
```

## Backup

```bash
# Database backup
docker compose exec postgres pg_dump -U user kamilya > backup_$(date +%Y%m%d).sql

# Restore
docker compose exec postgres psql -U user kamilya < backup_20260621.sql
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| API 502 | Check if api container is running: `docker compose ps` |
| Database connection | Verify DATABASE_URL in .env |
| Redis connection | Check Redis container: `docker compose logs redis` |
| CORS errors | Add domain to CORS_ORIGINS in .env |
| Rate limiting | Check Redis is running and rate limit config |
