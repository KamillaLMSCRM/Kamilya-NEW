import { defineConfig } from "drizzle-kit";

export default defineConfig({
  dialect: "postgresql",
  schema: "./schema/*.ts",
  out: "./migrations",
  strict: true,
  verbose: true,
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "postgresql://lms:lms_dev_password_2026@localhost:5432/kamilya_lms",
  },
});
