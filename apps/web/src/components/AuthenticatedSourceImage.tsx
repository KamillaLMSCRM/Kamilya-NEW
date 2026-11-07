'use client';

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

const uuid = '[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}';
const asset = 'asset-[0-9a-f]{64}';
const allowed = new RegExp(`^(?:/v1/documents/${uuid}/editorial-review/assets/${asset}\\?preparation_sha256=[0-9a-f]{64}|/v1/courses/${uuid}/lessons/${uuid}/source-assets/${asset})$`, 'i');
const frozenLessonImage = new RegExp(`^/v1/courses/${uuid}/lessons/${uuid}/source-assets/(${asset})$`, 'i');
const uuidOnly = new RegExp(`^${uuid}$`, 'i');

type ReviewImageContext = { attemptId: string; lessonId: string; token?: string };
const ReviewImageContext = createContext<ReviewImageContext | null>(null);

export function ReviewSourceImageProvider({ attemptId, lessonId, token, children }: ReviewImageContext & { children: ReactNode }) {
  const value = useMemo(() => ({ attemptId, lessonId, token }), [attemptId, lessonId, token]);
  return <ReviewImageContext.Provider value={value}>{children}</ReviewImageContext.Provider>;
}

export function isAllowedSourceImageUrl(url: string): boolean { return allowed.test(url); }
export function sourceImageLine(line: string): { alt: string; url: string } | null {
  const match = line.match(/^\s*!\[([^\]\n]*)\]\(([^\s()]+)\)\s*$/);
  return match && isAllowedSourceImageUrl(match[2]) ? { alt: match[1], url: match[2] } : null;
}

export function AuthenticatedSourceImage({ url, alt, loadingLabel, errorLabel, openLabel }: {
  url: string; alt: string; loadingLabel?: string; errorLabel?: string; openLabel?: string;
}) {
  const { lang } = useT();
  const labels = lang === 'kk' ? ['Сурет жүктелуде…', 'Суретті жүктеу мүмкін болмады', 'Суретті толық өлшемде ашу']
    : lang === 'en' ? ['Loading image…', 'Could not load image', 'Open full-size image']
    : ['Загрузка изображения…', 'Не удалось загрузить изображение', 'Открыть изображение в полном размере'];
  const sessionEpoch = useAuthStore(state => state.sessionEpoch);
  const review = useContext(ReviewImageContext);
  const matchedAsset = review ? frozenLessonImage.exec(url)?.[1] : undefined;
  const requestUrl = review
    ? (matchedAsset && uuidOnly.test(review.attemptId) && uuidOnly.test(review.lessonId)
      ? `/v1/course-review-attempts/${review.attemptId}/lessons/${review.lessonId}/source-assets/${matchedAsset}` : null)
    : (isAllowedSourceImageUrl(url) ? url : null);
  const [state, setState] = useState<{ url: string; epoch: number; review: ReviewImageContext | null; objectUrl?: string; failed?: boolean }>({ url: '', epoch: -1, review: null });
  useEffect(() => {
    if (!requestUrl) return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    setState({ url, epoch: sessionEpoch, review });
    const reviewConfig = review ? (review.token ? { headers: { Authorization: `Bearer ${review.token}` } }
      : { reviewerAccountSession: true }) : {};
    void api.get<Blob>(requestUrl, { responseType: 'blob', signal: controller.signal, ...reviewConfig }).then(({ data }) => {
      if (controller.signal.aborted) return;
      if (!/^image\/(?:png|jpeg|gif|webp)$/i.test(data.type)) throw new Error('Unsupported image type');
      objectUrl = URL.createObjectURL(data);
      setState({ url, epoch: sessionEpoch, review, objectUrl });
    }).catch(() => { if (!controller.signal.aborted) setState({ url, epoch: sessionEpoch, review, failed: true }); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url, requestUrl, sessionEpoch, review]);
  if (!requestUrl || (state.url === url && state.epoch === sessionEpoch && state.review === review && state.failed)) return <span role="status">{errorLabel ?? labels[1]}</span>;
  if (state.url !== url || state.epoch !== sessionEpoch || state.review !== review || !state.objectUrl) return <span role="status">{loadingLabel ?? labels[0]}</span>;
  return <a href={state.objectUrl} target="_blank" rel="noopener noreferrer" aria-label={`${openLabel ?? labels[2]}: ${alt}`} className="inline-block max-w-full focus-visible:ring-2 focus-visible:ring-ring">
    {/* Browser renders only a local object URL returned by the authenticated API. */}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={state.objectUrl} alt={alt} className="h-auto max-h-80 max-w-full rounded border border-border object-contain" />
  </a>;
}
