"""YouTube transcript acquisition — provider-neutral seam.

This module implements stages YTG-03/YTG-04 of the YouTube plan
(docs/plans/2026-08-29_youtube-course-generation-plan.md):

- canonical https URL allowlist and video-id extraction (SSRF guards);
- provider-neutral ``TranscriptProvider`` interface and ``TranscriptResult``;
- retryable vs terminal error taxonomy;
- normalization into the existing document/ingestion source pipeline;
- provenance fields (url, video id, title, language, retrieval time).

No video/audio is downloaded and no access controls are bypassed. Caption
acquisition runs in a bounded worker task, then stores an ordinary Kamilya
document and uses the existing document indexing pipeline.
"""
