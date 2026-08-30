import type { AppRole } from '@/lib/routeRegistry';

export type HelpLocale = 'ru' | 'kk' | 'en';

interface LocalizedText {
  ru: string;
  kk: string;
  en: string;
}

interface HelpTopicDefinition {
  id: string;
  paths: readonly string[];
  roles: readonly AppRole[];
  title: LocalizedText;
  purpose: LocalizedText;
  steps: readonly LocalizedText[];
  example: LocalizedText;
  result: LocalizedText;
  important: LocalizedText;
}

export interface ContextualHelpContent {
  id: string;
  title: string;
  purpose: string;
  steps: string[];
  example: string;
  result: string;
  important: string;
}

const text = (ru: string, kk: string, en: string): LocalizedText => ({ ru, kk, en });

const TOPICS: readonly HelpTopicDefinition[] = [
  {
    id: 'methodologist-dashboard', paths: ['/dashboard'], roles: ['methodologist'],
    title: text('Панель управления', 'Басқару панелі', 'Dashboard'),
    purpose: text('Краткая картина текущего обучения: что требует внимания, какие курсы и назначения активны.', 'Ағымдағы оқытудың қысқаша көрінісі: назарды не қажет етеді, қандай курстар мен тағайындаулар белсенді.', 'A concise view of current learning activity, active courses, assignments, and items needing attention.'),
    steps: [text('Проверьте показатели и предупреждения.', 'Көрсеткіштер мен ескертулерді тексеріңіз.', 'Review indicators and warnings.'), text('Откройте нужный объект из карточки.', 'Карточкадан қажетті нысанды ашыңыз.', 'Open the relevant item from its card.'), text('После действия вернитесь и убедитесь, что показатель обновился.', 'Әрекеттен кейін көрсеткіштің жаңарғанын тексеріңіз.', 'Return after the action and confirm the indicator changed.')],
    example: text('Если есть просроченные назначения, откройте их список и уточните срок или получателей.', 'Мерзімі өткен тағайындаулар болса, тізімді ашып, мерзімін немесе алушыларын нақтылаңыз.', 'If assignments are overdue, open the list and review the deadline or recipients.'),
    result: text('Вы понимаете, что делать следующим шагом.', 'Келесі қадамды түсінесіз.', 'You know the next operational action.'),
    important: text('Панель показывает состояние, но не заменяет проверку самого курса или назначения.', 'Панель күйді көрсетеді, бірақ курс не тағайындауды тексеруді алмастырмайды.', 'The dashboard summarizes state; it does not replace checking the course or assignment itself.'),
  },
  {
    id: 'ai-generation', paths: ['/ai/generate'], roles: ['methodologist'],
    title: text('AI-генерация', 'AI-генерация', 'AI generation'),
    purpose: text('Создание черновика курса из ваших документов и требований.', 'Құжаттарыңыз бен талаптарыңыздан курс жобасын жасау.', 'Create a draft course from your documents and requirements.'),
    steps: [text('Выберите проверенные исходные документы.', 'Тексерілген бастапқы құжаттарды таңдаңыз.', 'Choose verified source documents.'), text('Укажите аудиторию, цель и ограничения курса.', 'Аудиторияны, мақсатты және шектеулерді көрсетіңіз.', 'Specify the audience, objective, and constraints.'), text('Проверьте каждое утверждение и сохраните только как черновик до методической проверки.', 'Әр тұжырымды тексеріп, әдістемелік тексеруге дейін жоба ретінде сақтаңыз.', 'Verify every claim and keep the result as a draft until methodological review.')],
    example: text('Загрузите инструкцию по работе с кассой и попросите подготовить вводный курс для нового кассира.', 'Касса нұсқаулығын жүктеп, жаңа кассирге кіріспе курс дайындауды сұраңыз.', 'Upload a cash-desk procedure and request an introductory course for a new cashier.'),
    result: text('Появится редактируемый черновик, а не автоматически утверждённый курс.', 'Автоматты бекітілген курс емес, өңделетін жоба пайда болады.', 'You receive an editable draft, not an automatically approved course.'),
    important: text('AI может ошибаться. Ответственность за итоговый материал остаётся у методиста.', 'AI қателесуі мүмкін. Соңғы материалға әдіскер жауап береді.', 'AI can be wrong. The methodologist remains responsible for the final material.'),
  },
  {
    id: 'courses', paths: ['/courses'], roles: ['methodologist'],
    title: text('Курсы', 'Курстар', 'Courses'),
    purpose: text('Подготовка, проверка, публикация и обновление учебных материалов.', 'Оқу материалдарын дайындау, тексеру, жариялау және жаңарту.', 'Prepare, review, publish, and update learning content.'),
    steps: [text('Создайте курс или откройте черновик.', 'Курс жасаңыз немесе жобаны ашыңыз.', 'Create a course or open a draft.'), text('Проверьте содержание, тест и обязательные сведения.', 'Мазмұнды, тестті және міндетті мәліметтерді тексеріңіз.', 'Review content, assessment, and required details.'), text('Публикуйте только готовую версию, затем назначьте её сотрудникам.', 'Дайын нұсқаны ғана жариялап, қызметкерлерге тағайындаңыз.', 'Publish only the approved version, then assign it to employees.')],
    example: text('Курс «Вводный инструктаж» сначала проверяется ответственным, затем публикуется и назначается новичкам.', '«Кіріспе нұсқама» курсы алдымен тексеріліп, кейін жарияланып, жаңа қызметкерлерге тағайындалады.', 'An induction course is reviewed first, then published and assigned to new hires.'),
    result: text('Готовая управляемая версия курса с историей изменений.', 'Өзгерістер тарихы бар басқарылатын курс нұсқасы.', 'A controlled course version with change history.'),
    important: text('Черновик недоступен обучающимся, а изменение опубликованного курса требует повторной проверки.', 'Жоба оқушыларға қолжетімсіз; жарияланған курсты өзгерту қайта тексеруді қажет етеді.', 'Learners cannot see drafts, and published-course changes require another review.'),
  },
  {
    id: 'quizzes', paths: ['/quizzes'], roles: ['methodologist'],
    title: text('Конструктор тестов', 'Тест құрастырушысы', 'Quiz builder'),
    purpose: text('Проверка знаний по материалам курса с понятными критериями прохождения.', 'Курс материалдары бойынша білімді түсінікті өту талаптарымен тексеру.', 'Assess knowledge with clear passing criteria.'),
    steps: [text('Выберите курс и темы проверки.', 'Курс пен тексеру тақырыптарын таңдаңыз.', 'Choose the course and assessment topics.'), text('Добавьте однозначные вопросы и отметьте правильные ответы.', 'Нақты сұрақтар қосып, дұрыс жауаптарды белгілеңіз.', 'Add unambiguous questions and mark correct answers.'), text('Настройте проходной балл и проверьте тест как обучающийся.', 'Өту балын баптап, тестті оқушы ретінде тексеріңіз.', 'Set the passing score and preview the quiz as a learner.')],
    example: text('После курса по ИБ сотрудник отвечает на 10 вопросов и проходит при 8 правильных ответах.', 'ИБ курсынан кейін қызметкер 10 сұраққа жауап беріп, 8 дұрыс жауаппен өтеді.', 'After an information-security course, a learner passes with 8 correct answers out of 10.'),
    result: text('Тест, который можно связать с курсом и учитывать в результате обучения.', 'Курспен байланыстырып, оқу нәтижесінде есепке алуға болатын тест.', 'A quiz that can be linked to a course and included in learning results.'),
    important: text('Не используйте вопросы с несколькими трактовками и ответы, которых нет в материале.', 'Екіұшты сұрақтар мен материалда жоқ жауаптарды қолданбаңыз.', 'Avoid ambiguous questions and answers not supported by the learning material.'),
  },
  {
    id: 'documents', paths: ['/documents'], roles: ['methodologist'],
    title: text('Документы', 'Құжаттар', 'Documents'),
    purpose: text('Хранение утверждённых источников, из которых создаются и обновляются курсы.', 'Курстар жасалатын және жаңартылатын бекітілген дереккөздерді сақтау.', 'Store approved source documents used to create and update courses.'),
    steps: [text('Загрузите документ с понятным названием и владельцем.', 'Құжатты түсінікті атаумен және иесімен жүктеңіз.', 'Upload a document with a clear title and owner.'), text('Укажите версию, дату и область применения.', 'Нұсқасын, күнін және қолданылу аясын көрсетіңіз.', 'Record its version, date, and scope.'), text('При замене источника проверьте связанные курсы.', 'Дереккөз ауысқанда байланысты курстарды тексеріңіз.', 'When replacing a source, review linked courses.')],
    example: text('«Регламент кассовых операций, версия 3 от 01.08.2026» используется для курса кассиров.', '«Кассалық операциялар регламенті, 01.08.2026 күнгі 3-нұсқа» кассирлер курсына қолданылады.', '“Cash operations procedure, version 3 dated 1 Aug 2026” is linked to the cashier course.'),
    result: text('Понятно, на каком документе основан каждый курс.', 'Әр курстың қай құжатқа негізделгені түсінікті.', 'Each course has a traceable source.'),
    important: text('Не загружайте личные данные и документы без права использования.', 'Жеке деректерді және пайдалануға құқығы жоқ құжаттарды жүктемеңіз.', 'Do not upload personal data or documents you are not authorized to use.'),
  },
  {
    id: 'learning-paths', paths: ['/learning-paths'], roles: ['methodologist'],
    title: text('Программы обучения', 'Оқу бағдарламалары', 'Learning programs'),
    purpose: text('Последовательность нескольких курсов для роли, адаптации или обязательной подготовки.', 'Рөлге, бейімделуге немесе міндетті даярлыққа арналған бірнеше курстың реті.', 'An ordered set of courses for a role, onboarding, or required training.'),
    steps: [text('Определите цель и группу сотрудников.', 'Мақсат пен қызметкерлер тобын анықтаңыз.', 'Define the objective and employee group.'), text('Добавьте курсы в нужном порядке и задайте сроки.', 'Курстарды ретімен қосып, мерзімдерін белгілеңіз.', 'Add courses in order and set deadlines.'), text('Проверьте маршрут целиком и только затем назначайте.', 'Маршрутты толық тексеріп, содан кейін ғана тағайындаңыз.', 'Review the entire path before assigning it.')],
    example: text('Программа нового кассира: знакомство с компанией → кассовые операции → ИБ → итоговый тест.', 'Жаңа кассир бағдарламасы: компаниямен танысу → кассалық операциялар → ИБ → қорытынды тест.', 'New cashier program: company introduction → cash operations → information security → final quiz.'),
    result: text('Сотрудник получает понятный маршрут, а руководитель видит общий прогресс.', 'Қызметкер түсінікті маршрут алады, басшы жалпы прогресті көреді.', 'The learner gets a clear path and the manager sees overall progress.'),
    important: text('Программа не заменяет отдельные курсы: сначала подготовьте и опубликуйте их.', 'Бағдарлама жеке курстарды алмастырмайды: алдымен оларды дайындап, жариялаңыз.', 'A program does not replace its courses; prepare and publish them first.'),
  },
  {
    id: 'cohorts', paths: ['/cohorts'], roles: ['methodologist'],
    title: text('Группы сотрудников', 'Қызметкерлер топтары', 'Employee groups'),
    purpose: text('Объединение сотрудников для общего назначения и контроля.', 'Қызметкерлерді ортақ тағайындау және бақылау үшін біріктіру.', 'Group employees for shared assignment and monitoring.'),
    steps: [text('Создайте группу с понятным критерием.', 'Түсінікті өлшеммен топ жасаңыз.', 'Create a group with a clear criterion.'), text('Добавьте нужных сотрудников и проверьте состав.', 'Қажетті қызметкерлерді қосып, құрамын тексеріңіз.', 'Add employees and verify membership.'), text('Назначьте группе курс или программу.', 'Топқа курс не бағдарлама тағайындаңыз.', 'Assign a course or program to the group.')],
    example: text('Группа «Новые сотрудники — август» получает общую программу адаптации.', '«Тамыздағы жаңа қызметкерлер» тобы ортақ бейімделу бағдарламасын алады.', 'The “August new hires” group receives one onboarding program.'),
    result: text('Меньше ручных назначений и единый контроль группы.', 'Қолмен тағайындау азайып, топ бірыңғай бақыланады.', 'Fewer manual assignments and consistent group tracking.'),
    important: text('Перед назначением проверьте, что в группе нет лишних сотрудников.', 'Тағайындаудан бұрын топта артық қызметкерлер жоқ екенін тексеріңіз.', 'Before assigning, ensure the group contains only intended employees.'),
  },
  {
    id: 'staff', paths: ['/staff'], roles: ['methodologist'],
    title: text('Сотрудники и структура', 'Қызметкерлер және құрылым', 'Employees and structure'),
    purpose: text('Ведение филиалов, отделов, должностей и сотрудников компании.', 'Компания филиалдарын, бөлімдерін, лауазымдарын және қызметкерлерін жүргізу.', 'Manage branches, departments, positions, and employees.'),
    steps: [text('Сначала создайте филиалы и вложенные отделы.', 'Алдымен филиалдар мен ішкі бөлімдерді жасаңыз.', 'Create branches and nested departments first.'), text('Добавьте должности в нужные подразделения.', 'Лауазымдарды тиісті бөлімдерге қосыңыз.', 'Add positions to the correct units.'), text('Импортируйте или добавьте сотрудников и проверьте результат до назначения обучения.', 'Қызметкерлерді импорттап не қосып, оқу тағайындамас бұрын нәтижені тексеріңіз.', 'Import or add employees and verify the result before assigning learning.')],
    example: text('Филиал Павлодар → Операционный отдел → Кассир → сотрудник с табельным номером.', 'Павлодар филиалы → Операциялық бөлім → Кассир → табельдік нөмірі бар қызметкер.', 'Pavlodar branch → Operations department → Cashier → employee with personnel number.'),
    result: text('Организационная структура, на которую можно назначать правила и обучение.', 'Ережелер мен оқуды тағайындауға болатын ұйымдық құрылым.', 'An organization structure that can receive rules and learning assignments.'),
    important: text('Филиал и отдел — разные уровни. Перед импортом проверяйте предложение системы, а не применяйте файл вслепую.', 'Филиал мен бөлім — әртүрлі деңгей. Импорт алдында жүйе ұсынысын тексеріңіз.', 'A branch and a department are different levels. Review the proposed import before applying it.'),
  },
  {
    id: 'training-procedures', paths: ['/training-procedures'], roles: ['methodologist'],
    title: text('Процедуры обучения', 'Оқыту рәсімдері', 'Training procedures'),
    purpose: text('Описание того, как организация назначает, подтверждает и учитывает обучение.', 'Ұйымның оқуды қалай тағайындайтынын, растайтынын және есепке алатынын сипаттау.', 'Define how the organization assigns, confirms, and records learning.'),
    steps: [text('Выберите понятный тип процедуры.', 'Түсінікті рәсім түрін таңдаңыз.', 'Choose a clear procedure type.'), text('Заполните только применимые обязательные сведения.', 'Тек қолданылатын міндетті мәліметтерді толтырыңыз.', 'Complete only applicable required details.'), text('Согласуйте процедуру с ответственным и сохраните реквизиты утверждения.', 'Рәсімді жауапты тұлғамен келісіп, бекіту деректерін сақтаңыз.', 'Agree the procedure with its owner and record approval details.')],
    example: text('Для ознакомления с политикой фиксируется электронное подтверждение сотрудника после чтения.', 'Саясатпен танысу үшін қызметкер оқығаннан кейін электрондық растау береді.', 'For policy acknowledgement, the employee confirms electronically after reading.'),
    result: text('Единые правила процесса и понятные доказательства выполнения.', 'Бірыңғай процесс ережелері және түсінікті орындалу дәлелдері.', 'Consistent process rules and clear completion evidence.'),
    important: text('Не заполняйте технические или юридические поля наугад; уточните их у ответственного.', 'Техникалық не заңдық өрістерді болжап толтырмаңыз; жауапты тұлғадан нақтылаңыз.', 'Do not guess technical or legal values; confirm them with the responsible owner.'),
  },
  {
    id: 'training-retention', paths: ['/training-retention'], roles: ['methodologist'],
    title: text('Сроки хранения', 'Сақтау мерзімдері', 'Retention periods'),
    purpose: text('Просмотр утверждённых сроков хранения результатов и доказательств обучения.', 'Оқу нәтижелері мен дәлелдерін сақтаудың бекітілген мерзімдерін көру.', 'Review approved retention periods for learning results and evidence.'),
    steps: [text('Найдите нужный вид результата или доказательства.', 'Қажетті нәтиже немесе дәлел түрін табыңыз.', 'Find the relevant result or evidence type.'), text('Сверьте срок хранения и указанное основание.', 'Сақтау мерзімі мен көрсетілген негізді салыстырыңыз.', 'Review the retention period and its stated basis.'), text('Если политика отсутствует или требует изменения, обратитесь к администратору Kamilya.', 'Саясат жоқ немесе өзгерту қажет болса, Kamilya әкімшісіне хабарласыңыз.', 'If a policy is missing or needs adjustment, contact the Kamilya administrator.')],
    example: text('Результаты обязательного обучения хранятся 5 лет по внутренней политике организации.', 'Міндетті оқу нәтижелері ұйымның ішкі саясаты бойынша 5 жыл сақталады.', 'Required-training results are retained for five years under company policy.'),
    result: text('Понятно, сколько и на каком основании хранятся результаты обучения.', 'Оқу нәтижелерінің қанша уақыт және қандай негізде сақталатыны түсінікті.', 'You can see how long learning results are retained and on what basis.'),
    important: text('Методист не изменяет политики и не удаляет доказательства из этого раздела.', 'Әдіскер бұл бөлімде саясаттарды өзгертпейді және дәлелдерді жоймайды.', 'A methodologist cannot change policies or delete evidence from this section.'),
  },
  {
    id: 'candidate-assessments', paths: ['/candidate-assessments'], roles: ['methodologist'],
    title: text('Оценка кандидатов', 'Үміткерлерді бағалау', 'Candidate assessments'),
    purpose: text('Проверка знаний кандидата по требованиям конкретной роли.', 'Нақты рөл талаптары бойынша үміткер білімін тексеру.', 'Assess a candidate against the requirements of a specific role.'),
    steps: [text('Выберите должность и проверяемые знания.', 'Лауазым мен тексерілетін білімді таңдаңыз.', 'Choose the role and knowledge areas.'), text('Подготовьте тест без вопросов о чувствительных личных данных.', 'Сезімтал жеке деректер туралы сұрақтарсыз тест дайындаңыз.', 'Prepare a test without sensitive personal-data questions.'), text('Создайте ограниченную ссылку и оцените результат вместе с другими данными найма.', 'Шектеулі сілтеме жасап, нәтижені басқа жалдау деректерімен бірге бағалаңыз.', 'Create a limited link and review the result alongside other hiring evidence.')],
    example: text('Кандидат на кассира проходит тест по операциям и правилам безопасности.', 'Кассир үміткері операциялар мен қауіпсіздік ережелері бойынша тест өтеді.', 'A cashier candidate completes an operations and safety assessment.'),
    result: text('Сопоставимый результат проверки знаний, а не автоматическое решение о найме.', 'Жұмысқа алу туралы автоматты шешім емес, салыстырмалы білім нәтижесі.', 'A comparable knowledge result, not an automated hiring decision.'),
    important: text('Решение о найме принимает человек; тест — только один из источников.', 'Жұмысқа алу шешімін адам қабылдайды; тест — дереккөздердің бірі ғана.', 'A person makes the hiring decision; the assessment is only one input.'),
  },
  {
    id: 'assignments', paths: ['/assignments'], roles: ['methodologist'],
    title: text('Назначения и доступ', 'Тағайындаулар және қолжетімділік', 'Assignments and access'),
    purpose: text('Выдача сотрудникам опубликованного курса и выбор способа доступа.', 'Қызметкерлерге жарияланған курсты тағайындау және қолжетімділік тәсілін таңдау.', 'Assign a published course to employees and choose how they receive access.'),
    steps: [text('Выберите опубликованный материал.', 'Жарияланған материалды таңдаңыз.', 'Choose published learning content.'), text('Проверьте получателей и срок.', 'Алушылар мен мерзімді тексеріңіз.', 'Verify recipients and deadline.'), text('Создайте назначение и убедитесь, что доступ появился.', 'Тағайындау жасап, қолжетімділік ашылғанын тексеріңіз.', 'Create the assignment and confirm access is available.')],
    example: text('Курс по ИБ назначается всем кассирам двух филиалов до конца недели.', 'ИБ курсы екі филиалдың барлық кассирлеріне апта соңына дейін тағайындалады.', 'An information-security course is assigned to cashiers in two branches by week end.'),
    result: text('У сотрудников появляется обучение, а у методиста — контроль статусов.', 'Қызметкерлерде оқу, әдіскерде мәртебелерді бақылау пайда болады.', 'Learners receive access and the methodologist can track status.'),
    important: text('Перед массовым назначением проверьте выборку получателей на небольшом списке.', 'Жаппай тағайындаудан бұрын алушыларды шағын тізімде тексеріңіз.', 'Before a bulk assignment, validate the recipient selection on a small list.'),
  },
  {
    id: 'training-log', paths: ['/training-log'], roles: ['methodologist'],
    title: text('Журнал обучения', 'Оқу журналы', 'Training log'),
    purpose: text('Контроль назначений, прохождения, результатов и подтверждений.', 'Тағайындауларды, өтуді, нәтижелерді және растауларды бақылау.', 'Track assignments, completion, results, and confirmations.'),
    steps: [text('Отфильтруйте по сотруднику, подразделению или курсу.', 'Қызметкер, бөлім немесе курс бойынша сүзгілеңіз.', 'Filter by employee, unit, or course.'), text('Откройте запись и проверьте статус и основание.', 'Жазбаны ашып, мәртебе мен негізді тексеріңіз.', 'Open the record and verify status and basis.'), text('Экспортируйте только необходимый объём для согласованной цели.', 'Келісілген мақсат үшін тек қажетті көлемді экспорттаңыз.', 'Export only what is needed for an approved purpose.')],
    example: text('HR проверяет, кто из сотрудников филиала не завершил обязательный курс.', 'HR филиал қызметкерлерінің қайсысы міндетті курсты аяқтамағанын тексереді.', 'HR checks which branch employees have not completed a required course.'),
    result: text('Проверяемая картина обучения по сотрудникам и программам.', 'Қызметкерлер мен бағдарламалар бойынша тексерілетін оқу көрінісі.', 'A verifiable view of learning by employee and program.'),
    important: text('Журнал содержит служебные данные. Не передавайте выгрузки без рабочей необходимости.', 'Журналда қызметтік деректер бар. Қажетсіз экспорттарды бермеңіз.', 'The log contains operational data. Do not share exports without a business need.'),
  },
  {
    id: 'team', paths: ['/admin/team'], roles: ['admin'],
    title: text('Команда тенанта', 'Тенант командасы', 'Tenant team'),
    purpose: text('Добавление администраторов и методистов, которые управляют кабинетом.', 'Кабинетті басқаратын әкімшілер мен әдіскерлерді қосу.', 'Add administrators and methodologists who manage the tenant.'),
    steps: [text('Укажите корпоративный email, имя и роль.', 'Корпоративтік email, ат және рөлді көрсетіңіз.', 'Enter the corporate email, name, and role.'), text('Оставьте пароль пустым для входа по коду или задайте временный пароль.', 'Кодпен кіру үшін құпиясөзді бос қалдырыңыз немесе уақытша құпиясөз қойыңыз.', 'Leave password blank for email-code sign-in or set a temporary password.'), text('Проверьте сообщение об отправке инструкции и попросите пользователя войти.', 'Нұсқаулық жіберілгені туралы хабарды тексеріп, пайдаланушыдан кіруді сұраңыз.', 'Check the delivery message and ask the user to sign in.')],
    example: text('HR-методист добавляется без пароля и получает письмо со ссылкой на вход по коду.', 'HR-әдіскер құпиясөзсіз қосылып, кодпен кіру сілтемесі бар хат алады.', 'An HR methodologist is added without a password and receives code-first sign-in instructions.'),
    result: text('Активная учётная запись с нужной ролью и понятным способом первого входа.', 'Қажетті рөлі және түсінікті алғашқы кіру тәсілі бар белсенді аккаунт.', 'An active account with the correct role and a clear first sign-in path.'),
    important: text('Не создавайте общий аккаунт на нескольких людей и не передавайте личные пароли.', 'Бірнеше адамға ортақ аккаунт жасамаңыз және жеке құпиясөздерді бермеңіз.', 'Do not share one account among several people or distribute personal passwords.'),
  },
];

export const CONTEXTUAL_HELP_TOPIC_IDS = TOPICS.map((topic) => topic.id);

function pathMatches(pathname: string, candidate: string): boolean {
  return pathname === candidate || pathname.startsWith(`${candidate}/`);
}

function localized(value: LocalizedText, locale: string): string {
  return value[locale as HelpLocale] || value.ru;
}

export function getContextualHelp(
  pathname: string,
  role: string | null | undefined,
  locale: string,
): ContextualHelpContent | null {
  const topic = TOPICS.find(
    (candidate) => candidate.roles.includes(role as AppRole)
      && candidate.paths.some((path) => pathMatches(pathname, path)),
  );
  if (!topic) return null;
  return {
    id: topic.id,
    title: localized(topic.title, locale),
    purpose: localized(topic.purpose, locale),
    steps: topic.steps.map((step) => localized(step, locale)),
    example: localized(topic.example, locale),
    result: localized(topic.result, locale),
    important: localized(topic.important, locale),
  };
}
