const ru = {
  ownCourses: 'Ваши курсы',
  createFromDocuments: 'Создать из документов',
  manualCreate: 'Создать вручную',
  generationJobs: 'Задания генерации',
  loadedList: 'В текущем списке',
  first100: 'Показаны первые 100 курсов. Уточните фильтры, чтобы найти остальные.',
  filters: 'Поиск и фильтры курсов',
  searchLabel: 'Поиск',
  searchPlaceholder: 'Найти курс по названию',
  resetFilters: 'Сбросить фильтры',
  filteredEmpty: 'По выбранным условиям курсы не найдены',
  filteredEmptyHint: 'Измените запрос или сбросьте фильтры, чтобы вернуться к списку.',
  emptyHint: 'Создайте курс вручную, импортируйте SCORM или начните с AI.',
  nativeCourse: 'Учебный курс',
  openCourse: 'Открыть курс',
  selectedFile: 'Выбран файл',
};

type CatalogCopy = { [Key in keyof typeof ru]: string };

const kk: CatalogCopy = {
  ownCourses: 'Сіздің курстарыңыз',
  createFromDocuments: 'Құжаттардан жасау',
  manualCreate: 'Қолмен жасау',
  generationJobs: 'Генерация тапсырмалары',
  loadedList: 'Ағымдағы тізімде',
  first100: 'Алғашқы 100 курс көрсетілді. Қалғандарын табу үшін сүзгілерді нақтылаңыз.',
  filters: 'Курстарды іздеу және сүзу',
  searchLabel: 'Іздеу',
  searchPlaceholder: 'Курсты атауы бойынша табу',
  resetFilters: 'Сүзгілерді қалпына келтіру',
  filteredEmpty: 'Таңдалған шарттар бойынша курстар табылмады',
  filteredEmptyHint: 'Сұрауды өзгертіңіз немесе тізімге оралу үшін сүзгілерді қалпына келтіріңіз.',
  emptyHint: 'Курсты қолмен жасаңыз, SCORM импорттаңыз немесе AI арқылы бастаңыз.',
  nativeCourse: 'Оқу курсы',
  openCourse: 'Курсты ашу',
  selectedFile: 'Таңдалған файл',
};

const en: CatalogCopy = {
  ownCourses: 'Your courses',
  createFromDocuments: 'Create from documents',
  manualCreate: 'Create manually',
  generationJobs: 'Generation jobs',
  loadedList: 'In the current list',
  first100: 'The first 100 courses are shown. Narrow the filters to find the rest.',
  filters: 'Course search and filters',
  searchLabel: 'Search',
  searchPlaceholder: 'Find a course by title',
  resetFilters: 'Reset filters',
  filteredEmpty: 'No courses match these filters',
  filteredEmptyHint: 'Change your search or reset the filters to return to the list.',
  emptyHint: 'Create a course manually, import SCORM or start with AI.',
  nativeCourse: 'Learning course',
  openCourse: 'Open course',
  selectedFile: 'Selected file',
};

export const courseCatalogCopy = { ru, kk, en };

export function getCourseCatalogCopy(lang?: string): CatalogCopy {
  return lang === 'kk' ? kk : lang === 'en' ? en : ru;
}
