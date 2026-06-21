import { pgTable, uuid, text, timestamp, jsonb, boolean, integer, bigint } from "drizzle-orm/pg-core";
import { tenants } from "./tenants";
import { users } from "./users";

export const courses = pgTable("courses", {
  id: uuid("id").defaultRandom().primaryKey(),
  tenantId: uuid("tenant_id")
    .notNull()
    .references(() => tenants.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  description: text("description").notNull().default(""),
  status: text("status").notNull().default("draft"),
  thumbnailUrl: text("thumbnail_url"),
  createdBy: uuid("created_by"),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().notNull(),
  publishedAt: timestamp("published_at", { withTimezone: true }),
  aiGenerated: boolean("ai_generated").notNull().default(false),
});

export const modules = pgTable("modules", {
  id: uuid("id").defaultRandom().primaryKey(),
  courseId: uuid("course_id")
    .notNull()
    .references(() => courses.id, { onDelete: "cascade" }),
  tenantId: uuid("tenant_id")
    .notNull()
    .references(() => tenants.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  description: text("description").notNull(),
  orderIndex: integer("order_index").notNull().default(0),
  aiGenerated: boolean("ai_generated").notNull().default(false),
});

export const lessons = pgTable("lessons", {
  id: uuid("id").defaultRandom().primaryKey(),
  moduleId: uuid("module_id")
    .notNull()
    .references(() => modules.id, { onDelete: "cascade" }),
  tenantId: uuid("tenant_id")
    .notNull()
    .references(() => tenants.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  contentType: text("content_type").notNull().default("text"),
  content: text("content"),
  durationSeconds: integer("duration_seconds"),
  orderIndex: integer("order_index").notNull().default(0),
  aiGenerated: boolean("ai_generated").notNull().default(false),
  publishedAt: timestamp("published_at", { withTimezone: true }),
});

export const contentBlocks = pgTable("content_blocks", {
  id: uuid("id").defaultRandom().primaryKey(),
  lessonId: uuid("lesson_id")
    .notNull()
    .references(() => lessons.id, { onDelete: "cascade" }),
  type: text("type").notNull(),
  content: text("content"),
  orderIndex: integer("order_index").notNull().default(0),
  metadata: jsonb("metadata"),
});

export const quizzes = pgTable("quizzes", {
  id: uuid("id").defaultRandom().primaryKey(),
  lessonId: uuid("lesson_id")
    .notNull()
    .references(() => lessons.id, { onDelete: "cascade" }),
  tenantId: uuid("tenant_id")
    .notNull()
    .references(() => tenants.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  passScore: integer("pass_score").notNull().default(80),
  timeLimit: integer("time_limit"),
  attemptLimit: integer("attempt_limit").notNull().default(3),
});

export const questions = pgTable("questions", {
  id: uuid("id").defaultRandom().primaryKey(),
  quizId: uuid("quiz_id")
    .notNull()
    .references(() => quizzes.id, { onDelete: "cascade" }),
  text: text("text").notNull(),
  type: text("type").notNull(),
  points: integer("points").notNull().default(1),
  explanation: text("explanation"),
  orderIndex: integer("order_index").notNull().default(0),
  poolGroup: text("pool_group"),
});

export const quizChoices = pgTable("quiz_choices", {
  id: uuid("id").defaultRandom().primaryKey(),
  questionId: uuid("question_id")
    .notNull()
    .references(() => questions.id, { onDelete: "cascade" }),
  text: text("text").notNull(),
  isCorrect: boolean("is_correct").notNull().default(false),
  orderIndex: integer("order_index").notNull().default(0),
});

export const quizAttempts = pgTable("quiz_attempts", {
  id: uuid("id").defaultRandom().primaryKey(),
  quizId: uuid("quiz_id")
    .notNull()
    .references(() => quizzes.id, { onDelete: "cascade" }),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  tenantId: uuid("tenant_id")
    .notNull()
    .references(() => tenants.id, { onDelete: "cascade" }),
  startedAt: timestamp("started_at", { withTimezone: true }).defaultNow().notNull(),
  finishedAt: timestamp("finished_at", { withTimezone: true }),
  score: integer("score"),
  passed: boolean("passed"),
  answers: jsonb("answers"),
});

export const enrollments = pgTable("enrollments", {
  id: uuid("id").defaultRandom().primaryKey(),
  courseId: uuid("course_id")
    .notNull()
    .references(() => courses.id, { onDelete: "cascade" }),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  tenantId: uuid("tenant_id")
    .notNull()
    .references(() => tenants.id, { onDelete: "cascade" }),
  status: text("status").notNull().default("enrolled"),
  enrolledAt: timestamp("enrolled_at", { withTimezone: true }).defaultNow().notNull(),
  completedAt: timestamp("completed_at", { withTimezone: true }),
});

export const progress = pgTable("progress", {
  id: uuid("id").defaultRandom().primaryKey(),
  tenantId: uuid("tenant_id")
    .notNull()
    .references(() => tenants.id, { onDelete: "cascade" }),
  userId: uuid("user_id")
    .notNull()
    .references(() => users.id, { onDelete: "cascade" }),
  courseId: uuid("course_id")
    .notNull()
    .references(() => courses.id, { onDelete: "cascade" }),
  lessonId: uuid("lesson_id")
    .notNull()
    .references(() => lessons.id, { onDelete: "cascade" }),
  percent: integer("percent").notNull().default(0),
  timeSpent: integer("time_spent").notNull().default(0),
  completed: boolean("completed").notNull().default(false),
  lastAt: timestamp("last_at", { withTimezone: true }).defaultNow().notNull(),
});
