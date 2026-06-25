'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import {
  FileText,
  FileImage,
  Film,
  File,
  FolderOpen,
  Upload,
  Trash2,
  Plus,
} from 'lucide-react';

interface Document {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size: number;
  description: string;
  created_at: string;
}

export default function DocumentsPage() {
  const { t } = useT();
    const { confirm, dialog } = useConfirm();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await api.get('/v1/documents');
      setDocuments(Array.isArray(res.data) ? res.data : []);
    } catch {} finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      setSelectedFile(file);
      if (!title) setTitle(file.name.replace(/\.[^/.]+$/, ''));
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      if (!title) setTitle(file.name.replace(/\.[^/.]+$/, ''));
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('title', title || selectedFile.name);
    formData.append('description', description);
    try {
      await api.post('/v1/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      fetchDocuments();
      setShowUpload(false);
      setSelectedFile(null);
      setTitle('');
      setDescription('');
    } catch (e) {
      console.error('Upload failed', e);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: string) => {
        const ok = await confirm({
      title: t('dialogs.confirmDeleteDocument'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    await api.delete(`/v1/documents/${id}`);
    fetchDocuments();
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getFileIcon = (contentType: string) => {
    if (contentType.includes('pdf')) return <FileText className="w-5 h-5 text-destructive" />;
    if (contentType.includes('word') || contentType.includes('doc')) return <FileText className="w-5 h-5 text-primary" />;
    if (contentType.includes('image')) return <FileImage className="w-5 h-5 text-accent" />;
    if (contentType.includes('video')) return <Film className="w-5 h-5 text-warning" />;
    return <File className="w-5 h-5 text-muted-foreground" />;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground font-display">{t('documents.title')}</h1>
        <button onClick={() => setShowUpload(true)} className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary/90 transition-colors">
          + Загрузить документ
        </button>
      </div>

      {/* Upload modal */}
      {showUpload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => { setShowUpload(false); setSelectedFile(null); setTitle(''); setDescription(''); }} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-lg mx-4 p-6 z-10">
            <h2 className="text-lg font-bold text-foreground font-display mb-4">Загрузка документа</h2>

            {/* Drag & drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileRef.current?.click()}
              className={`rounded-2xl border-2 border-dashed p-8 text-center cursor-pointer transition-all ${
                dragOver ? 'border-primary bg-primary/5' : selectedFile ? 'border-success/40 bg-success/10' : 'border-border hover:border-border hover:bg-muted'
              }`}
            >
              <input ref={fileRef} type="file" onChange={handleFileSelect} className="hidden" accept=".pdf,.doc,.docx,.txt,.md,.pptx,.xlsx,.csv" />
              {selectedFile ? (
                <div className="space-y-2">
                  <div className="text-3xl">{getFileIcon(selectedFile.type)}</div>
                  <div className="text-sm font-medium text-foreground">{selectedFile.name}</div>
                  <div className="text-xs text-muted-foreground">{formatSize(selectedFile.size)}</div>
                  <button onClick={(e) => { e.stopPropagation(); setSelectedFile(null); }} className="text-xs text-primary hover:underline">Выбрать другой файл</button>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="text-3xl text-muted-foreground"><FolderOpen className="w-16 h-16 mx-auto" /></div>
                  <div className="text-sm text-muted-foreground">Перетащите файл сюда или нажмите для выбора</div>
                  <div className="text-xs text-muted-foreground">PDF, DOC, TXT, MD, PPTX, XLSX, CSV</div>
                </div>
              )}
            </div>

            {/* Title & description */}
            <div className="space-y-3 mt-4">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">Название</label>
                <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Название документа" className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">Описание</label>
                <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} placeholder="Краткое описание содержимого документа..." className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none" />
              </div>
            </div>

            <div className="flex gap-2 justify-end mt-5">
              <button onClick={() => { setShowUpload(false); setSelectedFile(null); setTitle(''); setDescription(''); }} className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors">Отмена</button>
              <button onClick={handleUpload} disabled={!selectedFile || uploading} className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50">
                {uploading ? 'Загрузка...' : 'Загрузить'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Documents list */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : documents.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border py-12 text-center">
          <div className="text-muted-foreground mb-3">
            <svg className="mx-auto" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>
            </svg>
          </div>
          <p className="text-muted-foreground text-sm">{t('documents.noDocuments')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => (
            <div key={doc.id} className="rounded-2xl border border-border bg-card p-4 shadow-card hover:shadow-card-hover transition-all">
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-lg shrink-0">
                  {getFileIcon(doc.content_type)}
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-bold text-foreground truncate">{doc.title}</h3>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-muted-foreground">{doc.filename}</span>
                    <span className="text-xs text-muted-foreground">·</span>
                    <span className="text-xs text-muted-foreground">{formatSize(doc.size)}</span>
                  </div>
                  {doc.description && <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{doc.description}</p>}
                </div>
                <button onClick={() => handleDelete(doc.id)} className="rounded-xl border border-destructive/40 px-3 py-1.5 text-xs text-destructive hover:border-destructive/40 hover:text-destructive transition-colors shrink-0">Удалить</button>
              </div>
            </div>
          ))}
        </div>
      )}
{dialog}
    </div>
  );
}
