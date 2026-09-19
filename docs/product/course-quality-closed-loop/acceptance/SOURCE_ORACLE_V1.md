# Source oracle V1

Status: accepted for implementation with the PDF limitation below.

## Exact inputs

- XLSX: approved local multi-sheet catalog fixture (not stored in Git)
  - SHA-256: `00783869F407800C94917053D84430091424DE2CF36108D4E972540CF8BC52BE`
  - Primary source: `Коллекции!B2:D17`.
  - `Коллекции!A19:D19` is metadata, not a product fact.
  - `Феникс и Чикаго!A2:H292` is supporting item-level evidence and must not override collection-level statements without an explicit conflict outcome.
- PDF: approved local image-only regulatory fixture (not stored in Git)
  - SHA-256: `A30C8F3DC158E2CA73A21535D3C28DDDBF9F0A7778E417A91255C628DFD6E605`
  - 21 image-only pages; `pypdf` extracts no embedded text.
  - Page/section roles and non-numeric rules may seed tests only after exact rendered/Docling quote verification. Thresholds, percentages, formulas, negations and cross-page clauses are not accepted from Windows OCR.

## XLSX assessable blocks

- Collection concept: `Коллекции!B2:D2`.
- Room scope and explicit exclusions: `Коллекции!B3:D3`.
- Style and colors: `Коллекции!B5:D6`.
- корпус/facade materials: `Коллекции!B7:D8`.
- Opening mechanisms: `Коллекции!B9:D9`.
- Guides: `Коллекции!B10:D10`.
- Cabinet, bed and chest characteristics: `Коллекции!B11:D13`.
- Comparison and recommendation distinctions: `Коллекции!B15:D17`.

Every assessment contract must identify one collection, one attribute and one exact value/claim. Alternative values may come from the same attribute row for another collection only when the question names the target collection. A value for a different function or attribute is not a distractor candidate.

## Negative-space cases

- `Нет сегмента` item rows are not a semantic collection.
- Missing source values remain unavailable; they are not inferred.
- `Феникс` and `Чикаго Стрит` having no beds does not mean the whole catalog has no compatible bed.
- Item-row facts are not generalized to an entire collection.
- PDF title/approval/TOC and page-21 form fields are not autonomous lessons or universal facts.
- Incomplete OCR fragments, isolated list items, formulas and cross-page clauses are unassessable until their complete source block is verified.
- Conditions, exceptions, optionality and negation must survive unchanged.

## Acceptance use

The XLSX locators above are the first RED/GREEN fixtures. PDF fixtures must carry an exact verified quote and converter/source identity. Replays may omit unsafe questions and report incomplete coverage; they must not pad counts, relax evidence checks or select only a favorable run.
