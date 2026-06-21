'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Table, Badge, Modal } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';

interface Document {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size: number;
  created_at: string;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [title, setTitle] = useState('');
  const token = useAuthStore((s) => s.token);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchDocuments = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/documents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setDocuments(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !token) return;

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', title || file.name);

    try {
      const res = await fetch(`${API_URL}/v1/documents/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (res.ok) {
        fetchDocuments();
        setShowModal(false);
        setTitle('');
      }
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Удалить документ?')) return;
    const res = await fetch(`${API_URL}/v1/documents/${id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) fetchDocuments();
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Документы</h1>
        <Button onClick={() => setShowModal(true)}>Загрузить документ</Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 text-gray-400">Загрузка...</div>
          ) : documents.length === 0 ? (
            <div className="p-6 text-gray-400">Документов пока нет</div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th className="text-left p-3">Название</th>
                  <th className="text-left p-3">Файл</th>
                  <th className="text-left p-3">Тип</th>
                  <th className="text-left p-3">Размер</th>
                  <th className="text-left p-3">Дата</th>
                  <th className="text-right p-3"></th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id} className="border-t">
                    <td className="p-3 font-medium">{doc.title}</td>
                    <td className="p-3 text-gray-500">{doc.filename}</td>
                    <td className="p-3">
                      <Badge variant="outline">{doc.content_type.split('/').pop()}</Badge>
                    </td>
                    <td className="p-3 text-gray-500">{formatSize(doc.size)}</td>
                    <td className="p-3 text-gray-500">{new Date(doc.created_at).toLocaleDateString('ru')}</td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => handleDelete(doc.id)}
                        className="text-red-500 hover:underline text-sm"
                      >
                        Удалить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal open={showModal} onOpenChange={setShowModal}>
        <CardHeader>
          <CardTitle>Загрузка документа</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Название (необязательно)</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full border rounded px-3 py-2"
              placeholder="Описание документа"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Файл</label>
            <input type="file" onChange={handleUpload} disabled={uploading} />
          </div>
          {uploading && <p className="text-sm text-blue-600">Загрузка...</p>}
        </CardContent>
      </Modal>
    </div>
  );
}
