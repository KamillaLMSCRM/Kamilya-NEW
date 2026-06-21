import { z } from "zod";

// --- Tenants ---
export const TenantCreateSchema = z.object({
  name: z.string().min(1).max(255),
  slug: z.string().min(1).max(63),
});

export const TenantSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  slug: z.string(),
  status: z.enum(["lead", "trial", "active", "suspended", "churned"]),
  plan: z.enum(["starter", "business", "enterprise"]),
  settings: z.record(z.any()).default({}),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type Tenant = z.infer<typeof TenantSchema>;
export type TenantCreate = z.infer<typeof TenantCreateSchema>;

// --- Users ---
export const UserSchema = z.object({
  id: z.string().uuid(),
  tenantId: z.string().uuid(),
  email: z.string().email().nullable(),
  telegramId: z.number().nullable(),
  passwordHash: z.string().nullable(),
  firstName: z.string(),
  lastName: z.string(),
  status: z.enum(["active", "inactive", "banned"]),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const UserCreateSchema = z.object({
  tenantId: z.string().uuid(),
  email: z.string().email(),
  telegramId: z.number().optional(),
  password: z.string().min(8),
  firstName: z.string().min(1),
  lastName: z.string().min(1),
});

export type User = z.infer<typeof UserSchema>;
export type UserCreate = z.infer<typeof UserCreateSchema>;

// --- Auth ---
export const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string(),
});

export const RefreshSchema = z.object({
  refreshToken: z.string(),
});

export const TokenSchema = z.object({
  accessToken: z.string(),
  refreshToken: z.string(),
  tokenType: z.string().default("bearer"),
  expiresIn: z.number(),
});

export type Login = z.infer<typeof LoginSchema>;
export type Token = z.infer<typeof TokenSchema>;

// --- Courses ---
export const CourseCreateSchema = z.object({
  title: z.string().min(1).max(255),
  description: z.string().max(5000).default(""),
  status: z.enum(["draft", "published", "archived"]).default("draft"),
});

export const CourseUpdateSchema = z.object({
  title: z.string().min(1).max(255).optional(),
  description: z.string().max(5000).optional(),
  status: z.enum(["draft", "published", "archived"]).optional(),
});

export const CourseSchema = z.object({
  id: z.string().uuid(),
  tenantId: z.string().uuid(),
  title: z.string(),
  description: z.string(),
  status: z.enum(["draft", "published", "archived"]),
  thumbnailUrl: z.string().nullable(),
  createdBy: z.string().uuid().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
  publishedAt: z.string().nullable(),
  aiGenerated: z.boolean(),
});

export type CourseCreate = z.infer<typeof CourseCreateSchema>;
export type CourseUpdate = z.infer<typeof CourseUpdateSchema>;
export type Course = z.infer<typeof CourseSchema>;
