-- Kamilya LMS Core v1.0 — Initial Database Schema
-- PostgreSQL 16

-- Enable pgvector extension for AI/ML features (v1.1+)
CREATE EXTENSION IF NOT EXISTS pgvector;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tenants schema
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'trial' CHECK (status IN ('lead', 'trial', 'active', 'suspended', 'churned')),
    plan TEXT NOT NULL DEFAULT 'starter' CHECK (plan IN ('starter', 'business', 'enterprise')),
    settings JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON tenants (status);
CREATE INDEX ON tenants (slug);

-- Users schema
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT,
    telegram_id BIGINT,
    password_hash TEXT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'banned')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON users (tenant_id);
CREATE INDEX ON users (email);
CREATE UNIQUE INDEX ON users (tenant_id, telegram_id) WHERE telegram_id IS NOT NULL;

-- User roles mapping
CREATE TABLE user_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('superadmin', 'admin', 'org_admin', 'teacher', 'student')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_role UNIQUE (user_id, tenant_id, role)
);

CREATE INDEX ON user_roles (tenant_id);
CREATE INDEX ON user_roles (user_id);

-- User sessions (refresh tokens)
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON user_sessions (user_id);
CREATE INDEX ON user_sessions (refresh_token);

-- Tenant settings
CREATE TABLE tenant_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    logo_url TEXT,
    primary_color TEXT CHECK (primary_color ~ '^#[0-9a-fA-F]{6}$'),
    default_language TEXT NOT NULL DEFAULT 'ru' CHECK (default_language IN ('ru', 'kk', 'en')),
    self_enrollment BOOLEAN NOT NULL DEFAULT false,
    quiz_pass_threshold INTEGER NOT NULL DEFAULT 80,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON tenant_settings (tenant_id);
