const COMPLETE_KZ_PHONE = /^\+7 \(\d{3}\) \d{3}-\d{2}-\d{2}$/;

export function formatKzPhone(value: string): string {
  const raw = value.trim();
  let digits = raw.replace(/\D/g, "");

  if (raw.startsWith("+7") || digits.startsWith("8") || (digits.length > 10 && digits.startsWith("7"))) {
    digits = digits.slice(1);
  }

  const local = digits.slice(0, 10);
  if (!local) return "";

  const area = local.slice(0, 3);
  const first = local.slice(3, 6);
  const second = local.slice(6, 8);
  const third = local.slice(8, 10);

  let formatted = `+7 (${area}`;
  if (area.length === 3) formatted += ")";
  if (first) formatted += ` ${first}`;
  if (second) formatted += `-${second}`;
  if (third) formatted += `-${third}`;
  return formatted;
}

export function isCompleteKzPhone(value: string): boolean {
  return COMPLETE_KZ_PHONE.test(value);
}
