'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button, Input } from 'ui-kit';
import { useAuthStore } from 'lib/store';

interface Course {
  id: string;
  title: string;
  status: string;
}

interface AIGenerationJob {
  id: string;
  status: string;
  course_id: string | null;
  progress: number;
  stage: string;
  message: string;
}

export default function AIGeneratePage() {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const [documents, setDocuments] = useState<string[]>([]);
  const [targetAudience, setTargetAudience] = useState('');
  const [numModules, setNumModules] = useState(3);
  const [language, setLanguage] = useState('ru');
  const [generating, setGenerating] = useState(false);
  const [currentJob, setCurrentJob] = useState<AIGenerationJob | null>(null);

  useEffect(() => {
    if (!token) return;
    fetch(`${API_URL}/v1/documents`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => res.json())
      .then((docs) => setDocuments(docs.map((d: any) => d.id)));
  }, [token, API_URL]);

  useEffect(() => {
    if (!currentJob || currentJob.status === 'completed' || currentJob.status === 'failed') return;

    const interval = setInterval(async () => {
      const res = await fetch(`${API_URL}/v1/ai/jobs/${currentJob.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const job = await res.json();
        setCurrentJob(job);
        if (job.status === 'completed' && job.course_id) {
          router.push(`/courses/${job.course_id}/edit`);
        }
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [currentJob, token, API_URL, router]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API_URL}/v1/ai/generate-course`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          documents,
          target_audience: targetAudience,
          num_modules: numModules,
          language,
        }),
      });
      if (res.ok) {
        const job = await res.json();
        setCurrentJob(job);
      }
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">AI Генерация курса</h1>

      <Card>
        <CardContent className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Целевая аудитория</label>
            <Input
              value={targetAudience}
              onChange={(e) => setTargetAudience(e.target.value)}
              placeholder="Опишите для кого этот курс..."
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Количество модулей</label>
              <Input
                type="number"
                min={1}
                max={10}
                value={numModules}
                onChange={(e) => setNumModules(parseInt(e.target.value) || 3)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Язык</label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full border rounded px-3 py-2"
              >
                <option value="ru">Русский</option>
                <option value="kk">Қазақша</option>
                <option value="en">English</option>
              </select>
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={handleGenerate} disabled={generating}>
              {generating ? 'Запуск...' : 'Генерировать курс'}
            </Button>
            <Button variant="outline" onClick={() => router.push('/courses')}>
              Отмена
            </Button>
          </div>
        </CardContent>
      </Card>

      {currentJob && (
        <Card>
          <CardHeader>
            <CardTitle>Прогресс генерации</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Статус:</span>
              <span className="text-sm">{currentJob.status}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Этап:</span>
              <span className="text-sm">{currentJob.stage}</span>
            </div>
            <div className="h-2 bg-gray-200 rounded">
              <div
                className="h-2 bg-blue-600 rounded transition-all"
                style={{ width: `${currentJob.progress}%` }}
              />
            </div>
            <p className="text-sm text-gray-500">{currentJob.message}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
