import { describe, expect, it } from "vitest";
import { formatKzPhone, isCompleteKzPhone } from "@/lib/kzPhone";

describe("Kazakhstan phone formatting", () => {
  it("formats local, country-code, and trunk-prefix input consistently", () => {
    expect(formatKzPhone("7771234567")).toBe("+7 (777) 123-45-67");
    expect(formatKzPhone("+7 777 123 45 67")).toBe("+7 (777) 123-45-67");
    expect(formatKzPhone("8 777 123 45 67")).toBe("+7 (777) 123-45-67");
  });

  it("keeps partial input editable and caps the number at ten local digits", () => {
    expect(formatKzPhone("7012")).toBe("+7 (701) 2");
    expect(formatKzPhone("+7 7771234567999")).toBe("+7 (777) 123-45-67");
  });

  it("accepts only a complete masked number for submission", () => {
    expect(isCompleteKzPhone("+7 (777) 123-45-67")).toBe(true);
    expect(isCompleteKzPhone("+7 (777) 123-45")).toBe(false);
    expect(isCompleteKzPhone("")).toBe(false);
  });
});
