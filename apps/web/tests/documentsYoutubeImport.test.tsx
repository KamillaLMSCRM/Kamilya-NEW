import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

const pageSource = fs.readFileSync(path.resolve(process.cwd(), 'src/app/documents/page.tsx'), 'utf8');

describe('documents YouTube import UI contract', () => {
  it('analyzes before confirmation and exposes both safe continuation actions', () => {
    expect(pageSource).toContain("api.post<YouTubeImportAccepted>('/v1/youtube/analyze'");
    expect(pageSource).toContain("`/v1/youtube/analyses/${youtubeAnalysisJobId}/confirm`");
    expect(pageSource).toContain("api.get<YouTubeImportStatus>(accepted.data.status_url.replace('/api', ''))");
    expect(pageSource).toContain("handleYoutubeConfirm('create_course')");
    expect(pageSource).toContain("handleYoutubeConfirm('save_captions')");
  });

  it('does not close the in-progress form when the backdrop is clicked', () => {
    expect(pageSource).toContain('<div className="absolute inset-0 bg-black/40" aria-hidden="true" />');
  });
});
