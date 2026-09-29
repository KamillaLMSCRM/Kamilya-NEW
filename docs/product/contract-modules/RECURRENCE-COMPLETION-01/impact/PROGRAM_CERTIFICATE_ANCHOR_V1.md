# Program certificate anchor V1

Status: Accepted

- Responsibility: select the completed final-course enrollment belonging to the
  exact completed learning-path assignment before issuing its certificate.
- Non-responsibilities: course completion, scoring, certificate rendering.
- Interface: existing `issue_learning_path_certificate` signature and return.
- Invariant: `certificate.learning_path_assignment_id` and
  `certificate.enrollment_id` refer to the same occurrence.
- Data ownership: certificate service reads assignments/enrollments and owns
  certificate creation; no other tables are mutated.
- Error mode: no matching exact enrollment means no certificate, never fallback
  to a manual or prior occurrence.
- Verification: competing manual/prior enrollment regression and existing
  certificate suite.
- Read scope: certificate service/models/tests. Write scope: exact query and
  its tests only.
- Stop: any required change to completion or assignment lifecycle.
- Done: exact public service behavior passes without changing its interface.
