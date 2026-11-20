import type { CourseLanguage } from './courseLanguages';

export type VideoClip = { video_id: string; start: number; end: number };
export type PracticeCopy = { question: string; choices: [string, string, string]; explanation: string };
export type VideoPractice = { at: number; correct_index: number; ru: PracticeCopy; kk: PracticeCopy };
export type PracticeState = {
  clip: VideoClip | null;
  revision: number;
  approved: VideoPractice | null;
  pending: boolean;
  proposal: { draft: VideoPractice; evidence: string } | null;
  error: string | null;
};

export const practicePath = (courseId: string, lessonId: string) =>
  '/v1/courses/' + encodeURIComponent(courseId) + '/lessons/' + encodeURIComponent(lessonId) + '/video-practice';

export const captionTime = (seconds: number) =>
  Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');

const copy = {
  ru: {
    title: 'Самопроверка по видео', prepare: 'Предложить вопрос из субтитров', pending: 'Готовится вопрос',
    evidence: 'Фрагмент субтитров', moment: 'Секунда видео', question: 'Вопрос', option: 'Вариант',
    explanation: 'Объяснение', correct: 'Правильный вариант', save: 'Показать в уроке', remove: 'Убрать из урока',
    approved: 'Вопрос доступен в уроке', refresh: 'Проверить состояние', error: 'Не удалось выполнить действие. Обновите состояние.',
    unavailable: 'Не удалось получить субтитры для этого видео.', noSource: 'Подходящий фрагмент субтитров не найден.',
    invalid: 'Ответ модели не удалось подтвердить по субтитрам.', unknown: 'Результат запроса пока не подтверждён.',
    answer: 'Ответить', skip: 'Пропустить', continue: 'Продолжить видео', right: 'Верно', wrong: 'Другой вариант верен',
    chooseLanguage: 'Язык вопроса',
  },
  kk: {
    title: 'Бейне бойынша өзін-өзі тексеру', prepare: 'Субтитрлерден сұрақ ұсыну', pending: 'Сұрақ дайындалып жатыр',
    evidence: 'Субтитр үзіндісі', moment: 'Бейненің секунды', question: 'Сұрақ', option: 'Жауап нұсқасы',
    explanation: 'Түсіндірме', correct: 'Дұрыс жауап', save: 'Сабақта көрсету', remove: 'Сабақтан алып тастау',
    approved: 'Сұрақ сабақта қолжетімді', refresh: 'Күйін тексеру', error: 'Әрекет орындалмады. Күйін жаңартыңыз.',
    unavailable: 'Бейненің субтитрлерін алу мүмкін болмады.', noSource: 'Субтитрден лайықты үзінді табылмады.',
    invalid: 'Модельдің жауабы субтитрмен расталмады.', unknown: 'Сұраудың нәтижесі әзірге расталған жоқ.',
    answer: 'Жауап беру', skip: 'Өткізіп жіберу', continue: 'Бейнені жалғастыру', right: 'Дұрыс', wrong: 'Басқа нұсқа дұрыс',
    chooseLanguage: 'Сұрақ тілі',
  },
  en: {
    title: 'Video self-check', prepare: 'Suggest a question from captions', pending: 'Preparing a question',
    evidence: 'Caption excerpt', moment: 'Video timestamp in seconds', question: 'Question', option: 'Choice',
    explanation: 'Explanation', correct: 'Correct choice', save: 'Show in lesson', remove: 'Remove from lesson',
    approved: 'Question available in lesson', refresh: 'Check status', error: 'The action failed. Refresh the status.',
    unavailable: 'Captions are unavailable for this video.', noSource: 'No suitable caption excerpt was found.',
    invalid: 'The model response could not be verified against the captions.', unknown: 'The request outcome is still unknown.',
    answer: 'Answer', skip: 'Skip', continue: 'Resume video', right: 'Correct', wrong: 'Another choice is correct',
    chooseLanguage: 'Question language',
  },
};

export const videoPracticeCopy = (language: CourseLanguage) => copy[language];

export const practiceMatches = (src: string, clip: VideoClip) => {
  const url = new URL(src);
  return url.pathname === '/embed/' + clip.video_id
    && url.searchParams.get('start') === String(clip.start)
    && url.searchParams.get('end') === String(clip.end);
};
