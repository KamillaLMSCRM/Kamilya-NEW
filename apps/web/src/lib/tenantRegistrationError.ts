const FIELD_LABELS: Record<string, string> = {
  company_name: 'Компания',
  contact_name: 'Контактное лицо',
  email: 'Email',
  password: 'Пароль',
  phone: 'Телефон',
  telegram_username: 'Telegram',
  employee_count_range: 'Размер компании',
  billing_identifier: 'БИН/ИИН',
  message: 'Комментарий',
};

export function getTenantRegistrationError(error: any): string {
  const detail = error?.response?.data?.detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        const field = Array.isArray(item?.loc) ? String(item.loc.at(-1) || '') : '';
        const label = FIELD_LABELS[field] || field;
        const message = typeof item?.msg === 'string' ? item.msg : '';
        return [label, message].filter(Boolean).join(': ');
      })
      .filter(Boolean);
    if (messages.length > 0) return messages.join('. ');
  }

  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message;
  }
  if (typeof detail === 'string') return detail;

  return 'Не удалось создать trial. Проверьте поля формы и попробуйте ещё раз.';
}
