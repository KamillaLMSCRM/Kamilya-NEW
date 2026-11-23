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

export function parseCaptionTime(value: string): number | null {
  const match = /^(\d+):([0-5]\d)$/.exec(value.trim());
  if (!match) return null;
  const seconds = Number(match[1]) * 60 + Number(match[2]);
  return Number.isSafeInteger(seconds) ? seconds : null;
}

const copy = {
  ru: {
    title: 'Самопроверка по видео', prepare: 'Предложить вопрос из субтитров', pending: 'Готовится вопрос',
    evidence: 'Фрагмент субтитров', moment: 'Таймкод (мин:сек)', question: 'Вопрос', option: 'Вариант',
    explanation: 'Объяснение', correct: 'Правильный вариант', save: 'Показать в уроке', remove: 'Убрать из урока',
    approved: 'Вопрос доступен в уроке', refresh: 'Проверить состояние', error: 'Не удалось выполнить действие. Обновите состояние.',
    unavailable: 'Не удалось получить субтитры для этого видео.', noSource: 'Подходящий фрагмент субтитров не найден.',
    providerUnavailable: 'Сервис получения субтитров сейчас недоступен.',
    languageUnavailable: 'Для этого видео не найдены субтитры на поддерживаемом языке.',
    videoUnavailable: 'Источник субтитров не смог открыть видео.',
    transcriptLimit: 'Субтитры превышают предел автоматической обработки.',
    captionFallback: 'Этот сбой касается автоматического подбора вопроса. Можно добавить вопрос вручную или загрузить субтитры этого видео.',
    checkCaptions: 'Проверить субтитры', captionsAvailable: 'Субтитры найдены. Можно предложить вопрос.',
    blocked: 'YouTube ограничил доступ к субтитрам. Можно добавить файл субтитров этого видео.',
    timeout: 'Сервис субтитров не ответил. Повторите попытку или добавьте файл.',
    subtitleFile: 'Субтитры этого видео (.srt или .vtt)', fileQuestion: 'Предложить вопрос из файла',
    invalidFile: 'Не удалось прочитать субтитры. Выберите файл SRT или VTT с таймкодами.',
    useProposal: 'Использовать предложенный вопрос',
    invalid: 'Ответ модели не удалось подтвердить по субтитрам.', unknown: 'Результат запроса пока не подтверждён.',
    answer: 'Ответить', skip: 'Пропустить', continue: 'Продолжить видео', right: 'Верно', wrong: 'Другой вариант верен',
    chooseLanguage: 'Язык вопроса', add: 'Добавить вопрос', preview: 'Предпросмотр видео',
    pickCurrent: 'Взять текущий момент', timingUnavailable: 'Плеер не передал время. Введите таймкод вручную.',
    invalidTime: 'Введите таймкод в формате мин:сек внутри фрагмента.', close: 'Закрыть', cancel: 'Отмена',
  },
  kk: {
    title: 'Бейне бойынша өзін-өзі тексеру', prepare: 'Субтитрлерден сұрақ ұсыну', pending: 'Сұрақ дайындалып жатыр',
    evidence: 'Субтитр үзіндісі', moment: 'Бейне уақыты (мин:сек)', question: 'Сұрақ', option: 'Жауап нұсқасы',
    explanation: 'Түсіндірме', correct: 'Дұрыс жауап', save: 'Сабақта көрсету', remove: 'Сабақтан алып тастау',
    approved: 'Сұрақ сабақта қолжетімді', refresh: 'Күйін тексеру', error: 'Әрекет орындалмады. Күйін жаңартыңыз.',
    unavailable: 'Бейненің субтитрлерін алу мүмкін болмады.', noSource: 'Субтитрден лайықты үзінді табылмады.',
    providerUnavailable: 'Субтитрлерді алу қызметі қазір қолжетімсіз.',
    languageUnavailable: 'Бұл бейнеге қолдау көрсетілетін тілдегі субтитрлер табылмады.',
    videoUnavailable: 'Субтитр көзі бейнені аша алмады.',
    transcriptLimit: 'Субтитрлер автоматты өңдеу шегінен асады.',
    captionFallback: 'Бұл қате сұрақты автоматты ұсынуға қатысты. Сұрақты қолмен қосуға немесе бейненің субтитрлерін жүктеуге болады.',
    checkCaptions: 'Субтитрлерді тексеру', captionsAvailable: 'Субтитрлер табылды. Сұрақ ұсынуға болады.',
    blocked: 'YouTube субтитрлерге қолжетімділікті шектеді. Осы бейненің субтитр файлын қосуға болады.',
    timeout: 'Субтитр қызметі жауап бермеді. Қайталап көріңіз немесе файл қосыңыз.',
    subtitleFile: 'Осы бейненің субтитрлері (.srt немесе .vtt)', fileQuestion: 'Файлдан сұрақ ұсыну',
    invalidFile: 'Субтитрлер оқылмады. Уақыт белгілері бар SRT немесе VTT файлын таңдаңыз.',
    useProposal: 'Ұсынылған сұрақты қолдану',
    invalid: 'Модельдің жауабы субтитрмен расталмады.', unknown: 'Сұраудың нәтижесі әзірге расталған жоқ.',
    answer: 'Жауап беру', skip: 'Өткізіп жіберу', continue: 'Бейнені жалғастыру', right: 'Дұрыс', wrong: 'Басқа нұсқа дұрыс',
    chooseLanguage: 'Сұрақ тілі', add: 'Сұрақ қосу', preview: 'Бейнені алдын ала көру',
    pickCurrent: 'Ағымдағы уақытты алу', timingUnavailable: 'Ойнатқыш уақытты жібермеді. Уақытты қолмен енгізіңіз.',
    invalidTime: 'Үзінді ішіндегі уақытты мин:сек пішімінде енгізіңіз.', close: 'Жабу', cancel: 'Бас тарту',
  },
  en: {
    title: 'Video self-check', prepare: 'Suggest a question from captions', pending: 'Preparing a question',
    evidence: 'Caption excerpt', moment: 'Timestamp (min:sec)', question: 'Question', option: 'Choice',
    explanation: 'Explanation', correct: 'Correct choice', save: 'Show in lesson', remove: 'Remove from lesson',
    approved: 'Question available in lesson', refresh: 'Check status', error: 'The action failed. Refresh the status.',
    unavailable: 'Captions are unavailable for this video.', noSource: 'No suitable caption excerpt was found.',
    providerUnavailable: 'The caption service is currently unavailable.',
    languageUnavailable: 'No captions in a supported language were found for this video.',
    videoUnavailable: 'The caption service could not open the video.',
    transcriptLimit: 'Captions exceed the automatic processing limit.',
    captionFallback: 'This affects automatic question suggestions. Add a question manually or upload captions for this video.',
    checkCaptions: 'Check captions', captionsAvailable: 'Captions found. A question can now be suggested.',
    blocked: 'YouTube restricted caption access. You can attach a caption file for this video.',
    timeout: 'The caption service did not respond. Try again or attach a caption file.',
    subtitleFile: 'Captions for this video (.srt or .vtt)', fileQuestion: 'Suggest a question from the file',
    invalidFile: 'Could not read the captions. Choose an SRT or VTT file with timestamps.',
    useProposal: 'Use suggested question',
    invalid: 'The model response could not be verified against the captions.', unknown: 'The request outcome is still unknown.',
    answer: 'Answer', skip: 'Skip', continue: 'Resume video', right: 'Correct', wrong: 'Another choice is correct',
    chooseLanguage: 'Question language', add: 'Add a question', preview: 'Video preview',
    pickCurrent: 'Use current time', timingUnavailable: 'Player timing is unavailable. Enter the timestamp manually.',
    invalidTime: 'Enter a timestamp inside the clip in min:sec format.', close: 'Close', cancel: 'Cancel',
  },
};

export const videoPracticeCopy = (language: CourseLanguage) => copy[language];

export const practiceMatches = (src: string, clip: VideoClip) => {
  const url = new URL(src);
  return url.pathname === '/embed/' + clip.video_id
    && url.searchParams.get('start') === String(clip.start)
    && url.searchParams.get('end') === String(clip.end);
};
