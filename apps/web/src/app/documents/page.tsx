'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  AlertCircle,
  ArrowRight,
  Download,
  File,
  FileImage,
  FileText,
  Film,
  FolderOpen,
  Loader2,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Trash2,
  Upload,
} from 'lucide-react';

import { toast } from '@/components/ui/Toast';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import {
  documentDeleteError,
  type DocumentCatalogItem,
  type DocumentCatalogResponse,
  type DocumentCategory,
  type DocumentIndexStatus,
  type DocumentJobAccepted,
  type DocumentLifecycleStatus,
  type DocumentUsageResponse,
} from '@/lib/documentCatalog';

const PAGE_SIZE = 25;

export default function DocumentsPage() {
  const { t } = useT();
  const { confirm, dialog } = useConfirm();
  const fileRef = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<DocumentCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<'all' | DocumentCategory>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | DocumentIndexStatus>('all');
  const [lifecycleFilter, setLifecycleFilter] = useState<DocumentLifecycleStatus>('active');

  const [showUpload, setShowUpload] = useState(false);
  const [versionSource, setVersionSource] = useState<DocumentCatalogItem | null>(null);
  const [duplicateConflict, setDuplicateConflict] = useState<{
    id: string;
    title: string;
    filename: string;
    version: number;
  } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState<DocumentCategory>('general');
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [reindexingId, setReindexingId] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [usageDocument, setUsageDocument] = useState<DocumentCatalogItem | null>(null);
  const [usageData, setUsageData] = useState<DocumentUsageResponse | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);

  const fetchDocuments = useCallback(async (append = false, cursor?: string | null) => {
    append ? setLoadingMore(true) : setLoading(true);
    setLoadError('');
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        include: 'usages_summary',
      });
      if (search.trim()) params.set('q', search.trim());
      if (categoryFilter !== 'all') params.set('category', categoryFilter);
      if (statusFilter !== 'all') params.set('index_status', statusFilter);
      params.set('lifecycle_status', lifecycleFilter);
      if (cursor) params.set('cursor', cursor);
      const response = await api.get<DocumentCatalogResponse>(`/v1/documents/catalog?${params.toString()}`);
      setDocuments((current) => append ? [...current, ...response.data.items] : response.data.items);
      setNextCursor(response.data.page.next_cursor);
      setHasMore(response.data.page.has_more);
    } catch (error) {
      console.error('Document catalog load failed', error);
      setLoadError(t('documents.loadFailed'));
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [categoryFilter, lifecycleFilter, search, statusFilter, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void fetchDocuments(), 250);
    return () => window.clearTimeout(timer);
  }, [fetchDocuments]);

  const resetUpload = () => {
    setShowUpload(false);
    setVersionSource(null);
    setDuplicateConflict(null);
    setSelectedFile(null);
    setTitle('');
    setDescription('');
    setCategory('general');
    setDragOver(false);
  };

  const openUpload = (source?: DocumentCatalogItem) => {
    setVersionSource(source || null);
    setDuplicateConflict(null);
    setSelectedFile(null);
    setTitle(source?.title || '');
    setDescription(source?.description || '');
    setCategory(source?.category || 'general');
    setShowUpload(true);
  };

  const chooseFile = (file?: File) => {
    if (!file) return;
    setDuplicateConflict(null);
    setSelectedFile(file);
    setTitle((current) => current || file.name.replace(/\.[^/.]+$/, ''));
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('title', title.trim() || selectedFile.name);
    formData.append('description', description.trim());
    formData.append('category', category);
    if (versionSource) formData.append('new_version_of', versionSource.id);
    try {
      await api.post('/v1/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      resetUpload();
      toast.success(t('documents.uploadSuccess'));
      await fetchDocuments();
    } catch (error: any) {
      const detail = error?.response?.data?.details ?? error?.response?.data?.detail;
      if (detail?.code === 'duplicate_document' && detail.existing) {
        setDuplicateConflict(detail.existing);
        return;
      }
      toast.error(t('documents.uploadFailed'), {
        description: typeof detail === 'string' ? detail : t('documents.uploadFailedHint'),
      });
    } finally {
      setUploading(false);
    }
  };

  const pollDocumentJob = async (jobId: string, successMessage: string) => {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      try {
        const response = await api.get(`/v1/ai/jobs/${jobId}`);
        if (response.data.status === 'completed') {
          toast.success(successMessage);
          await fetchDocuments();
          return;
        }
        if (['failed', 'cancelled'].includes(response.data.status)) {
          toast.error(t('documents.backgroundJobFailed'), {
            description: response.data.message || t('documents.retry'),
          });
          await fetchDocuments();
          return;
        }
      } catch (error) {
        console.error('Document job polling failed', error);
      }
    }
    await fetchDocuments();
  };

  const handleReindex = async (document: DocumentCatalogItem) => {
    setReindexingId(document.id);
    try {
      const response = await api.post<DocumentJobAccepted>(
        `/v1/documents/${document.id}/reindex`
      );
      setDocuments((items) => items.map((item) => (
        item.id === document.id
          ? {
              ...item,
              index: {
                ...item.index,
                status: 'processing',
                revision: response.data.revision || item.index.revision,
                error_code: null,
                message: null,
              },
            }
          : item
      )));
      toast.success(t('documents.reindexStarted'), { description: document.title });
      void pollDocumentJob(response.data.job_id, t('documents.reindexCompleted'));
    } catch (error) {
      toast.error(t('documents.reindexFailed'), {
        description: documentDeleteError(error),
      });
    } finally {
      setReindexingId(null);
    }
  };

  const handleDownload = async (document: DocumentCatalogItem) => {
    setDownloadingId(document.id);
    try {
      const response = await api.get(`/v1/documents/${document.id}/download`, {
        responseType: 'blob',
      });
      const href = URL.createObjectURL(response.data);
      const anchor = window.document.createElement('a');
      anchor.href = href;
      anchor.download = document.filename;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (error) {
      console.error('Document download failed', error);
      toast.error(t('documents.downloadFailed'));
    } finally {
      setDownloadingId(null);
    }
  };

  const openUsages = async (document: DocumentCatalogItem) => {
    setUsageDocument(document);
    setUsageData(null);
    setUsageLoading(true);
    try {
      const response = await api.get<DocumentUsageResponse>(
        `/v1/documents/${document.id}/usages?limit=100`
      );
      setUsageData(response.data);
    } catch (error) {
      console.error('Document usages load failed', error);
      toast.error(t('documents.usagesLoadFailed'));
      setUsageDocument(null);
    } finally {
      setUsageLoading(false);
    }
  };

  const handleDelete = async (document: DocumentCatalogItem) => {
    const ok = await confirm({
      title: t('dialogs.confirmDeleteDocument'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    setDeletingId(document.id);
    try {
      await api.delete(`/v1/documents/${document.id}`);
      setDocuments((items) => items.filter((item) => item.id !== document.id));
      toast.success(t('documents.deleteStarted'), { description: document.title });
    } catch (error) {
      const detail = (error as any)?.response?.data?.details
        ?? (error as any)?.response?.data?.detail;
      if (detail?.code === 'document_in_use') {
        await openUsages(document);
      }
      toast.error(t('documents.deleteFailed'), {
        description: documentDeleteError(error),
        duration: 7000,
      });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold text-foreground">{t('documents.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('documents.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={() => openUpload()}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          {t('documents.upload')}
        </button>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-border pb-3" role="tablist" aria-label={t('documents.libraryViews')}>
        {([
          ['active', t('documents.activeDocuments')],
          ['delete_failed', t('documents.requiresAttention')],
          ['deletion_pending', t('documents.deletingDocuments')],
        ] as Array<[DocumentLifecycleStatus, string]>).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={lifecycleFilter === value}
            onClick={() => setLifecycleFilter(value)}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              lifecycleFilter === value
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid gap-3 border-b border-border pb-4 lg:grid-cols-[minmax(240px,1fr)_220px_220px]">
        <label className="relative">
          <span className="sr-only">{t('documents.search')}</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('documents.searchPlaceholder')}
            className="h-10 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm outline-none transition-colors focus:border-primary"
          />
        </label>
        <select
          value={categoryFilter}
          onChange={(event) => setCategoryFilter(event.target.value as 'all' | DocumentCategory)}
          className="h-10 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary"
          aria-label={t('documents.category')}
        >
          <option value="all">{t('documents.allCategories')}</option>
          <option value="general">{t('documents.categoryGeneral')}</option>
          <option value="job_instruction">{t('documents.categoryInstruction')}</option>
        </select>
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as 'all' | DocumentIndexStatus)}
          className="h-10 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-primary"
          aria-label={t('documents.indexStatus')}
        >
          <option value="all">{t('documents.allStatuses')}</option>
          <option value="ready">{t('documents.statusReady')}</option>
          <option value="partial">{t('documents.statusPartial')}</option>
          <option value="processing">{t('documents.statusProcessing')}</option>
          <option value="failed">{t('documents.statusFailed')}</option>
        </select>
      </div>

      {loading ? (
        <div className="flex min-h-48 items-center justify-center" aria-label={t('common.loading')}>
          <Loader2 className="h-7 w-7 animate-spin text-primary" />
        </div>
      ) : loadError ? (
        <div className="flex min-h-48 flex-col items-center justify-center gap-3 border border-destructive/30 bg-destructive/5 p-6 text-center">
          <AlertCircle className="h-7 w-7 text-destructive" />
          <p className="text-sm text-destructive">{loadError}</p>
          <button
            type="button"
            onClick={() => void fetchDocuments()}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted"
          >
            <RefreshCw className="h-4 w-4" />
            {t('documents.retry')}
          </button>
        </div>
      ) : documents.length === 0 ? (
        <div className="flex min-h-48 flex-col items-center justify-center gap-2 border border-dashed border-border p-6 text-center">
          <FolderOpen className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">{t('documents.noDocuments')}</p>
          <p className="text-xs text-muted-foreground">{t('documents.noDocumentsHint')}</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <div className="hidden grid-cols-[minmax(240px,1fr)_145px_145px_90px_105px_168px] gap-3 border-b border-border bg-muted/40 px-4 py-2 text-xs font-semibold text-muted-foreground lg:grid">
            <span>{t('documents.name')}</span>
            <span>{t('documents.category')}</span>
            <span>{t('documents.indexStatus')}</span>
            <span>{t('documents.version')}</span>
            <span>{t('documents.usedIn')}</span>
            <span className="text-right">{t('documents.actions')}</span>
          </div>
          {documents.map((document) => (
            <DocumentRow
              key={document.id}
              document={document}
              deleting={deletingId === document.id}
              reindexing={reindexingId === document.id}
              downloading={downloadingId === document.id}
              onDelete={() => void handleDelete(document)}
              onDownload={() => void handleDownload(document)}
              onReindex={() => void handleReindex(document)}
              onUploadVersion={() => openUpload(document)}
              onOpenUsages={() => void openUsages(document)}
              formatSize={formatSize}
              t={t}
            />
          ))}
        </div>
      )}

      {hasMore && !loading && !loadError && (
        <div className="flex justify-center">
          <button
            type="button"
            disabled={loadingMore}
            onClick={() => void fetchDocuments(true, nextCursor)}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
          >
            {loadingMore && <Loader2 className="h-4 w-4 animate-spin" />}
            {t('documents.loadMore')}
          </button>
        </div>
      )}

      {showUpload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button className="absolute inset-0 bg-black/40" onClick={resetUpload} aria-label={t('common.close')} />
          <section className="relative z-10 w-full max-w-lg rounded-lg bg-card p-5 shadow-card-lg" role="dialog" aria-modal="true">
            <h2 className="font-display text-lg font-bold">
              {versionSource ? t('documents.uploadVersionTitle') : t('documents.uploadTitle')}
            </h2>
            {versionSource && (
              <p className="mt-1 text-sm text-muted-foreground">
                {t('documents.uploadVersionHint', {
                  title: versionSource.title,
                  version: versionSource.version + 1,
                })}
              </p>
            )}
            <div
              onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(event) => { event.preventDefault(); setDragOver(false); chooseFile(event.dataTransfer.files[0]); }}
              onClick={() => fileRef.current?.click()}
              className={`mt-4 cursor-pointer rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
                dragOver ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'
              }`}
            >
              <input
                ref={fileRef}
                type="file"
                className="hidden"
                accept=".pdf,.doc,.docx,.txt,.md,.xlsx,.csv"
                onChange={(event) => chooseFile(event.target.files?.[0])}
              />
              {selectedFile ? (
                <>
                  <Upload className="mx-auto h-7 w-7 text-primary" />
                  <p className="mt-2 break-all text-sm font-medium">{selectedFile.name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{formatSize(selectedFile.size)}</p>
                </>
              ) : (
                <>
                  <FolderOpen className="mx-auto h-8 w-8 text-muted-foreground" />
                  <p className="mt-2 text-sm text-muted-foreground">{t('documents.dragDropHint')}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{t('documents.allowedTypes')}</p>
                </>
              )}
            </div>
            <div className="mt-4 grid gap-3">
              <label className="grid gap-1 text-sm">
                <span className="font-medium">{t('documents.name')}</span>
                <input value={title} onChange={(event) => setTitle(event.target.value)} className="h-10 rounded-lg border border-border bg-background px-3 outline-none focus:border-primary" />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-medium">{t('documents.category')}</span>
                <select
                  value={category}
                  disabled={Boolean(versionSource)}
                  onChange={(event) => setCategory(event.target.value as DocumentCategory)}
                  className="h-10 rounded-lg border border-border bg-background px-3 outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <option value="general">{t('documents.categoryGeneral')}</option>
                  <option value="job_instruction">{t('documents.categoryInstruction')}</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span className="font-medium">{t('documents.description')}</span>
                <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} className="resize-none rounded-lg border border-border bg-background px-3 py-2 outline-none focus:border-primary" />
              </label>
            </div>
            {duplicateConflict && (
              <div className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
                <p className="font-semibold text-foreground">{t('documents.duplicateTitle')}</p>
                <p className="mt-1 text-muted-foreground">
                  {t('documents.duplicateHint', {
                    title: duplicateConflict.title,
                    version: duplicateConflict.version,
                  })}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    const titleToFind = duplicateConflict.title;
                    resetUpload();
                    setLifecycleFilter('active');
                    setSearch(titleToFind);
                  }}
                  className="mt-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted"
                >
                  {t('documents.showExisting')}
                </button>
              </div>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={resetUpload} className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted">
                {t('common.cancel')}
              </button>
              <button
                type="button"
                disabled={!selectedFile || uploading}
                onClick={() => void handleUpload()}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {uploading && <Loader2 className="h-4 w-4 animate-spin" />}
                {uploading ? t('documents.uploading') : t('documents.upload')}
              </button>
            </div>
          </section>
        </div>
      )}

      {usageDocument && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            onClick={() => setUsageDocument(null)}
            aria-label={t('common.close')}
          />
          <section className="relative z-10 max-h-[85vh] w-full max-w-2xl overflow-auto rounded-lg bg-card p-5 shadow-card-lg" role="dialog" aria-modal="true">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-display text-lg font-bold">{t('documents.usagesTitle')}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{usageDocument.title}</p>
              </div>
              <button type="button" onClick={() => setUsageDocument(null)} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted">
                {t('common.close')}
              </button>
            </div>
            {usageLoading ? (
              <div className="flex min-h-32 items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : usageData?.items.length ? (
              <>
                <p className="mt-4 text-sm text-muted-foreground">
                  {t('documents.usagesDeleteHint', { count: usageData.summary.total })}
                </p>
                <div className="mt-3 divide-y divide-border overflow-hidden rounded-lg border border-border">
                  {usageData.items.map((usage) => (
                    <div key={`${usage.type}-${usage.id}`} className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">{usage.title}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {t(`documents.usageType.${usage.type}` as any)}
                          {usage.status ? ` · ${usage.status}` : ''}
                        </p>
                      </div>
                      <Link
                        href={usage.route}
                        className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-primary hover:bg-primary/10"
                        title={t('documents.openUsage')}
                        aria-label={`${t('documents.openUsage')}: ${usage.title}`}
                      >
                        <ArrowRight className="h-4 w-4" />
                      </Link>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="mt-5 text-sm text-muted-foreground">{t('documents.notUsed')}</p>
            )}
          </section>
        </div>
      )}
      {dialog}
    </div>
  );
}

function DocumentRow({
  document,
  deleting,
  reindexing,
  downloading,
  onDelete,
  onDownload,
  onReindex,
  onUploadVersion,
  onOpenUsages,
  formatSize,
  t,
}: {
  document: DocumentCatalogItem;
  deleting: boolean;
  reindexing: boolean;
  downloading: boolean;
  onDelete: () => void;
  onDownload: () => void;
  onReindex: () => void;
  onUploadVersion: () => void;
  onOpenUsages: () => void;
  formatSize: (value: number) => string;
  t: (key: any, params?: Record<string, string | number>) => string;
}) {
  const usage = document.usages_summary;
  const isActive = document.lifecycle_status === 'active';
  return (
    <div className="grid gap-3 border-b border-border px-4 py-3 last:border-b-0 lg:grid-cols-[minmax(240px,1fr)_145px_145px_90px_105px_168px] lg:items-center">
      <div className="flex min-w-0 items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">
          {fileIcon(document.content_type)}
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{document.title}</p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">{document.filename} · {formatSize(document.size)}</p>
          {document.description && <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{document.description}</p>}
        </div>
      </div>
      <div className="text-sm text-foreground">
        <span className="mr-2 text-xs text-muted-foreground lg:hidden">{t('documents.category')}:</span>
        {document.category === 'job_instruction' ? t('documents.categoryInstruction') : t('documents.categoryGeneral')}
      </div>
      <div>
        <StatusBadge document={document} t={t} />
      </div>
      <div className="text-sm text-foreground">
        <span className="mr-2 text-xs text-muted-foreground lg:hidden">{t('documents.version')}:</span>
        <span>v{document.version}</span>
        {document.is_latest && (
          <span className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
            {t('documents.latestVersion')}
          </span>
        )}
      </div>
      <div className="text-sm text-foreground">
        <span className="mr-2 text-xs text-muted-foreground lg:hidden">{t('documents.usedIn')}:</span>
        {usage?.total ? (
          <button type="button" onClick={onOpenUsages} className="text-primary underline-offset-2 hover:underline">
            {t('documents.usageCount', { count: usage.total })}
          </button>
        ) : t('documents.notUsed')}
      </div>
      <div className="flex items-center justify-end gap-1">
        <button
          type="button"
          disabled={downloading}
          onClick={onDownload}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
          title={t('documents.download')}
          aria-label={`${t('documents.download')}: ${document.title}`}
        >
          {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        </button>
        {isActive && (
          <>
            <button
              type="button"
              disabled={reindexing || document.index.status === 'processing'}
              onClick={onReindex}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
              title={t('documents.reindex')}
              aria-label={`${t('documents.reindex')}: ${document.title}`}
            >
              {reindexing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}
            </button>
            <button
              type="button"
              onClick={onUploadVersion}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title={t('documents.uploadNewVersion')}
              aria-label={`${t('documents.uploadNewVersion')}: ${document.title}`}
            >
              <Upload className="h-4 w-4" />
            </button>
          </>
        )}
        <button
          type="button"
          disabled={deleting}
          onClick={onDelete}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
          title={
            document.lifecycle_status === 'delete_failed'
              ? t('documents.retryDelete')
              : document.lifecycle_status === 'deletion_pending'
                ? t('documents.retryCleanup')
                : t('dialogs.delete')
          }
          aria-label={`${
            document.lifecycle_status === 'delete_failed'
              ? t('documents.retryDelete')
              : document.lifecycle_status === 'deletion_pending'
                ? t('documents.retryCleanup')
                : t('dialogs.delete')
          }: ${document.title}`}
        >
          {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}

function StatusBadge({ document, t }: { document: DocumentCatalogItem; t: (key: any) => string }) {
  if (document.lifecycle_status === 'deletion_pending') {
    return (
      <span className="inline-flex rounded-full border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
        {t('documents.deletionPendingStatus')}
      </span>
    );
  }
  if (document.lifecycle_status === 'delete_failed') {
    return (
      <span
        className="inline-flex rounded-full border border-destructive/30 bg-destructive/10 px-2 py-1 text-xs font-medium text-destructive"
        title={document.deletion_error_message || undefined}
      >
        {t('documents.deletionFailedStatus')}
      </span>
    );
  }
  const config = {
    ready: ['bg-success/10 text-success border-success/30', t('documents.statusReady')],
    partial: ['bg-warning/10 text-warning border-warning/30', t('documents.statusPartial')],
    processing: ['bg-primary/10 text-primary border-primary/30', t('documents.statusProcessing')],
    failed: ['bg-destructive/10 text-destructive border-destructive/30', t('documents.statusFailed')],
  }[document.index.status];
  return (
    <span className={`inline-flex rounded-full border px-2 py-1 text-xs font-medium ${config[0]}`} title={document.index.message || undefined}>
      {config[1]}
    </span>
  );
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileIcon(contentType: string) {
  if (contentType.includes('pdf')) return <FileText className="h-5 w-5 text-destructive" />;
  if (contentType.includes('word') || contentType.includes('document')) return <FileText className="h-5 w-5 text-primary" />;
  if (contentType.includes('image')) return <FileImage className="h-5 w-5 text-accent" />;
  if (contentType.includes('video')) return <Film className="h-5 w-5 text-warning" />;
  return <File className="h-5 w-5 text-muted-foreground" />;
}
