# Bilingual native courses

Owner: Kamilya product owner. Scope: separate feature branch and DEV acceptance.

The course, lesson, quiz, question, choice, enrollment and certificate identifiers remain shared. A course author chooses Russian and/or Kazakh once before creating a course. The existing generator builds the canonical course once. A language edition translates its text; editors review the candidate before learners can select it.

Language editions belong to the tenant, course and digest of the canonical learning material. The digest covers question scoring and source references. Published translations are immutable for that digest. Existing learners resolve editions against the release attached to their assignment. Adding a compatible language edition does not fork a course, replace a release, create attempts or issue certificates.

Directed path: generation request → canonical course → version-bound language edition → author review → assignment email → language-specific lesson and quiz reading → existing grading, completion and certificate modules. The editor is tenant-authorized, learner reads use existing assignments and access windows, and a learner never receives answer keys through locale metadata. A selected quiz language lasts through that quiz session.

Default generation selection is Russian and Kazakh. One language is allowed. Existing courses maintain their current text until an author records its language. The pilot supports native course materials, shared media and associated native quizzes. SCORM remains on its own embedded localization path.

Acceptance: local contract and UI checks. Existing KARLSKRONA course in DEV retains its prior enrollment/certificates while adding Russian. An ordinary synthetic tenant starts with a simple source and verifies one bilingual course, one assignment email link, shared scores and one certificate. Translation and content quality are checked separately from delivery. Changes beyond this scope require product-owner agreement.
