const ru = {
  ownCourses: 'Ваши курсы',
  createFromDocuments: 'Создать из документов',
  manualCreate: 'Создать вручную',
  generationJobs: 'Задания генерации',
  loadedList: 'В текущем списке',
  first100: 'Показаны первые 100 курсов. Уточните фильтры, чтобы найти остальные.',
  pageSize: 'До 100 курсов на странице. Общий итог не рассчитан.',
  pagination: 'Страницы каталога', previousPage: 'Предыдущая страница', nextPage: 'Следующая страница', page: 'Страница',
  backToList: 'К списку курсов', emptyPage: 'На этой странице больше нет курсов',
  filters: 'Поиск и фильтры курсов',
  searchLabel: 'Поиск',
  searchPlaceholder: 'Найти курс по названию',
  resetFilters: 'Сбросить фильтры',
  filteredEmpty: 'По выбранным условиям курсы не найдены',
  filteredEmptyHint: 'Измените запрос или сбросьте фильтры, чтобы вернуться к списку.',
  emptyHint: 'Создайте курс из документов или вручную.',
  nativeCourse: 'Учебный курс',
  openCourse: 'Открыть курс',
};

type CatalogCopy = { [Key in keyof typeof ru]: string };

const kk: CatalogCopy = {
  ownCourses: 'Сіздің курстарыңыз',
  createFromDocuments: 'Құжаттардан жасау',
  manualCreate: 'Қолмен жасау',
  generationJobs: 'Генерация тапсырмалары',
  loadedList: 'Ағымдағы тізімде',
  first100: 'Алғашқы 100 курс көрсетілді. Қалғандарын табу үшін сүзгілерді нақтылаңыз.',
  pageSize: 'Бір бетте 100 курсқа дейін. Жалпы саны есептелмеген.',
  pagination: 'Каталог беттері', previousPage: 'Алдыңғы бет', nextPage: 'Келесі бет', page: 'Бет',
  backToList: 'Курстар тізіміне', emptyPage: 'Бұл бетте басқа курс жоқ',
  filters: 'Курстарды іздеу және сүзу',
  searchLabel: 'Іздеу',
  searchPlaceholder: 'Курсты атауы бойынша табу',
  resetFilters: 'Сүзгілерді қалпына келтіру',
  filteredEmpty: 'Таңдалған шарттар бойынша курстар табылмады',
  filteredEmptyHint: 'Сұрауды өзгертіңіз немесе тізімге оралу үшін сүзгілерді қалпына келтіріңіз.',
  emptyHint: 'Курсты құжаттардан немесе қолмен жасаңыз.',
  nativeCourse: 'Оқу курсы',
  openCourse: 'Курсты ашу',
};

const en: CatalogCopy = {
  ownCourses: 'Your courses',
  createFromDocuments: 'Create from documents',
  manualCreate: 'Create manually',
  generationJobs: 'Generation jobs',
  loadedList: 'In the current list',
  first100: 'The first 100 courses are shown. Narrow the filters to find the rest.',
  pageSize: 'Up to 100 courses per page. The overall total is not calculated.',
  pagination: 'Catalogue pages', previousPage: 'Previous page', nextPage: 'Next page', page: 'Page',
  backToList: 'Back to course list', emptyPage: 'There are no more courses on this page',
  filters: 'Course search and filters',
  searchLabel: 'Search',
  searchPlaceholder: 'Find a course by title',
  resetFilters: 'Reset filters',
  filteredEmpty: 'No courses match these filters',
  filteredEmptyHint: 'Change your search or reset the filters to return to the list.',
  emptyHint: 'Create a course from documents or manually.',
  nativeCourse: 'Learning course',
  openCourse: 'Open course',
};

export const courseCatalogCopy = { ru, kk, en };

export function getCourseCatalogCopy(lang?: string): CatalogCopy {
  return lang === 'kk' ? kk : lang === 'en' ? en : ru;
}
