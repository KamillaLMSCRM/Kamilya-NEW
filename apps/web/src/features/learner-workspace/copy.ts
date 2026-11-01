export const learnerWorkspaceCopy = {
  ru: {
    next: 'Следующее назначение', outline: 'Оглавление курса', help: 'Помощь по уроку', lesson: 'Урок',
    learningHint: 'Изучайте материал в удобном темпе. Обязательные проверки и завершение курса — отдельные шаги.',
    materialDone: 'Материал изучен',
    result: 'Результат проверки знаний', passHint: 'Тест пройден. Это не означает завершение всего курса.',
    failHint: 'Проходной балл не набран. Вернитесь к материалу перед следующей попыткой.',
    exhausted: 'Попытки исчерпаны. Обратитесь к методисту, чтобы уточнить дальнейшие действия.',
    attemptsRemaining: 'Осталось попыток', confirmationNotRequired: 'Подтверждение не требуется',
    noConfirmationHint: 'Для этого результата дополнительное подтверждение не требуется.',
    download: 'Скачать результат теста', preparing: 'Подготовка PDF…', downloadPdf: 'Скачать PDF',
    downloadFailed: 'Не удалось скачать результат теста. Повторите попытку.',
    legacyDownload: 'Бланк для этой попытки недоступен. Обратитесь к методисту: он проверит результат в журнале обучения.',
  },
  kk: {
    next: 'Келесі тағайындау', outline: 'Курс мазмұны', help: 'Сабақ бойынша көмек', lesson: 'Сабақ',
    learningHint: 'Материалды өз қарқыныңызбен оқыңыз. Міндетті тексерулер мен курсты аяқтау — бөлек қадамдар.',
    materialDone: 'Материал оқылды',
    result: 'Білімді тексеру нәтижесі', passHint: 'Тесттен өттіңіз. Бұл бүкіл курстың аяқталғанын білдірмейді.',
    failHint: 'Өту балы жиналмады. Келесі әрекетке дейін материалға оралыңыз.',
    exhausted: 'Әрекеттер таусылды. Келесі қадамдарды нақтылау үшін әдіскерге хабарласыңыз.',
    attemptsRemaining: 'Қалған әрекеттер', confirmationNotRequired: 'Растау қажет емес',
    noConfirmationHint: 'Бұл нәтиже үшін қосымша растау қажет емес.',
    download: 'Тест нәтижесін жүктеу', preparing: 'PDF дайындалуда…', downloadPdf: 'PDF жүктеу',
    downloadFailed: 'Тест нәтижесін жүктеу мүмкін болмады. Қайталап көріңіз.',
    legacyDownload: 'Бұл әрекеттің бланкі қолжетімсіз. Әдіскер нәтижені оқу журналынан тексере алады.',
  },
  en: {
    next: 'Next assignment', outline: 'Course outline', help: 'Lesson help', lesson: 'Lesson',
    learningHint: 'Read at your own pace. Required checks and course completion are separate steps.',
    materialDone: 'Material studied',
    result: 'Knowledge check result', passHint: 'You passed the test. This does not mean the whole course is complete.',
    failHint: 'The pass score was not reached. Review the material before your next attempt.',
    exhausted: 'No attempts remain. Ask your methodologist about the next steps.',
    attemptsRemaining: 'Attempts remaining', confirmationNotRequired: 'Confirmation not required',
    noConfirmationHint: 'No additional confirmation is required for this result.',
    download: 'Download test result', preparing: 'Preparing PDF…', downloadPdf: 'Download PDF',
    downloadFailed: 'Could not download the test result. Please try again.',
    legacyDownload: 'The result sheet for this attempt is unavailable. Your methodologist can check the training log.',
  },
} as const;

export function getLearnerWorkspaceCopy(lang: string) {
  return learnerWorkspaceCopy[lang === 'kk' || lang === 'en' ? lang : 'ru'];
}

export function isFocusedLearnerRoute(role: string | undefined, pathname: string) {
  return role === 'student' && (/^\/courses\/[^/]+\/?$/.test(pathname)
    || /^\/courses\/quiz\/[^/]+\/?$/.test(pathname));
}
