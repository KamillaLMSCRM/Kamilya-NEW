const DISPLAY_DATE_PATTERN = /^(\d{2})\/(\d{2})\/(\d{4})$/;
const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function isRealDate(year: number, month: number, day: number): boolean {
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day
  );
}

export function displayDateToIso(value: string): string | null {
  const match = DISPLAY_DATE_PATTERN.exec(value.trim());
  if (!match) return null;

  const [, dayText, monthText, yearText] = match;
  if (!isRealDate(Number(yearText), Number(monthText), Number(dayText))) return null;
  return `${yearText}-${monthText}-${dayText}`;
}

export function isoDateToDisplay(value: string): string {
  if (!value) return '';
  const match = ISO_DATE_PATTERN.exec(value.slice(0, 10));
  if (!match) return value;

  const [, yearText, monthText, dayText] = match;
  if (!isRealDate(Number(yearText), Number(monthText), Number(dayText))) return value;
  return `${dayText}/${monthText}/${yearText}`;
}

export function maskDisplayDate(value: string): string {
  if (ISO_DATE_PATTERN.test(value.trim())) return isoDateToDisplay(value);

  const digits = value.replace(/\D/g, '').slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}
