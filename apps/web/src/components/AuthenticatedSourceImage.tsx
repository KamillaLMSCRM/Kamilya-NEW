'use client';

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

const uuid = '[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}';
const asset = 'asset-[0-9a-f]{64}';
const uploaded = 'illustration-[0-9a-f]{64}\\.(?:png|jpg)';
const lessonAsset = '(?:' + asset + '|' + uploaded + ')';
const uploadedPath = new RegExp('^/v1/courses/' + uuid + '/lessons/' + uuid + '/source-assets/' + uploaded + '$');
export function isUploadedLessonImage(url: string): boolean { return uploadedPath.test(url); }

export function lessonImageMarkdown(url: string, alt: string, caption?: string): string {
  const escaped = alt.replace(/[\\[\]]/g, '\\$&');
  return '![' + escaped + '](' + url + (caption !== undefined ? ' ' + JSON.stringify(caption) : '') + ')';
}
const allowed = new RegExp(`^(?:/v1/documents/${uuid}/editorial-review/assets/${asset}\\?preparation_sha256=[0-9a-f]{64}|/v1/courses/${uuid}/lessons/${uuid}/source-assets/${lessonAsset})$`, 'i');
const frozenLessonImage = new RegExp(`^/v1/courses/${uuid}/lessons/${uuid}/source-assets/(${lessonAsset})$`, 'i');
const uuidOnly = new RegExp(`^${uuid}$`, 'i');

type ReviewImageContext = { attemptId: string; lessonId: string; token?: string };
const ReviewImageContext = createContext<ReviewImageContext | null>(null);

export function ReviewSourceImageProvider({ attemptId, lessonId, token, children }: ReviewImageContext & { children: ReactNode }) {
  const value = useMemo(() => ({ attemptId, lessonId, token }), [attemptId, lessonId, token]);
  return <ReviewImageContext.Provider value={value}>{children}</ReviewImageContext.Provider>;
}

export function isAllowedSourceImageUrl(url: string): boolean { return allowed.test(url); }
export function sourceImageLine(line: string): { alt: string; url: string; caption?: string } | null {
  const text = line.trim();
  if (!text.startsWith('![') || !text.endsWith(')') || /[\r\n]/.test(text)) return null;
  let alt = '';
  let boundary = 2;
  for (; boundary < text.length; boundary += 1) {
    const char = text[boundary];
    if (char === '\\' && /[\\[\]]/.test(text[boundary + 1] ?? '')) alt += text[++boundary];
    else if (char === ']') break;
    else alt += char;
  }
  if (text[boundary + 1] !== '(') return null;
  const target = text.slice(boundary + 2, -1);
  const space = target.indexOf(' ');
  const url = space < 0 ? target : target.slice(0, space);
  if (!isAllowedSourceImageUrl(url)) return null;
  let caption: string | undefined;
  if (space >= 0) {
    if (!isUploadedLessonImage(url)) return null;
    try {
      const parsed: unknown = JSON.parse(target.slice(space + 1));
      if (typeof parsed !== 'string' || /[\r\n]/.test(parsed)) return null;
      caption = parsed;
    } catch {
      return null;
    }
  }
  return caption === undefined ? { alt, url } : { alt, url, caption };
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
