const ru = {
  known: 'Показано {shown} из {total}.', unknown: 'Показано {shown}; общий итог неизвестен.',
  order: 'Порядок исходного списка сохранён.', drafts: 'Все черновики', jobs: 'Открыть задания генерации',
  jobsBound: 'Проверены последние 20 заданий, а не вся история.',
  reviewBound: 'Проверены первые 100 курсов, а не весь каталог.',
  trainingBound: 'Проверена только часть записей обучения; общее число проблем неизвестно.',
  localEmpty: 'В загруженной части списка таких задач нет.', mandatory: 'Обязательное обучение',
  unavailable: 'Данные временно недоступны.',
};
type Copy = { [Key in keyof typeof ru]: string };
const en: Copy = {
  known: 'Showing {shown} of {total}.', unknown: 'Showing {shown}; the overall total is unknown.',
  order: 'The source list order is preserved.', drafts: 'All drafts', jobs: 'Open generation jobs',
  jobsBound: 'Only the latest 20 jobs were checked, not the full history.',
  reviewBound: 'Only the first 100 courses were checked, not the full catalogue.',
  trainingBound: 'Only part of the training records was checked; the total number of issues is unknown.',
  localEmpty: 'No matching tasks in the loaded part of the list.', mandatory: 'Mandatory training',
  unavailable: 'Data is temporarily unavailable.',
};
const kk: Copy = {
  known: '{total} жазбаның {shown} көрсетілді.', unknown: '{shown} жазба көрсетілді; жалпы саны белгісіз.',
  order: 'Бастапқы тізімнің реті сақталды.', drafts: 'Барлық жобалар', jobs: 'Генерация тапсырмаларын ашу',
  jobsBound: 'Толық тарих емес, соңғы 20 тапсырма тексерілді.',
  reviewBound: 'Толық каталог емес, алғашқы 100 курс тексерілді.',
  trainingBound: 'Оқу жазбаларының бір бөлігі ғана тексерілді; мәселелердің жалпы саны белгісіз.',
  localEmpty: 'Тізімнің жүктелген бөлігінде мұндай тапсырма жоқ.', mandatory: 'Міндетті оқыту',
  unavailable: 'Деректер уақытша қолжетімсіз.',
};
export function getQueueCopy(lang: string): Copy { return lang === 'kk' ? kk : lang === 'en' ? en : ru; }
export function queueScope(lang: string, shown: number, total: number | null): string {
  const copy = getQueueCopy(lang);
  return (total === null ? copy.unknown : copy.known).replace('{shown}', String(shown)).replace('{total}', String(total));
}
