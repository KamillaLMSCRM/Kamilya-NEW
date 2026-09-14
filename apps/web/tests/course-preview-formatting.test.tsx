import { describe, expect, it } from "vitest";

import { formatLessonPreview } from "../src/app/ai/generate/components/CoursePreview";


describe("formatLessonPreview", () => {
  it("removes heading markers and a repeated lesson title", () => {
    expect(
      formatLessonPreview(
        "# Коллекция: Феникс\n\n## Что это за коллекция\n\nКраткое описание.",
        "Коллекция: Феникс",
      ),
    ).toBe("Что это за коллекция · Краткое описание.");
  });

  it("turns markdown tables into readable preview text", () => {
    expect(
      formatLessonPreview(
        "| Характеристика | Значение |\n| --- | --- |\n| Материал | ЛДСП |",
      ),
    ).toBe("Характеристика — Значение · Материал — ЛДСП");
  });

  it("formats a table row truncated by the API without a closing delimiter", () => {
    expect(formatLessonPreview("| Феникс | Модульная коллекция…")).toBe(
      "Феникс — Модульная коллекция…",
    );
  });

  it("keeps editing markup out of the read-only preview", () => {
    const preview = formatLessonPreview("### **Важно**\n- Используйте `каталог`.");

    expect(preview).toBe("Важно · • Используйте каталог.");
    expect(preview).not.toContain("#");
    expect(preview).not.toContain("**");
    expect(preview).not.toContain("`");
  });
});
