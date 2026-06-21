import React from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Input } from '@/components/ui';

interface CourseEditorProps {
  course: { id: string; title: string; description: string; status: string };
}

export default function CourseEditor({ course }: CourseEditorProps) {
  return (
    <div className="grid grid-cols-3 gap-6">
      {/* Left: Module/Lesson outline */}
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Структура</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button variant="outline" className="w-full justify-start">
              + Добавить модуль
            </Button>
            <div className="mt-4 space-y-2">
              <p className="text-sm text-gray-600 font-medium">Модуль 1</p>
              <div className="ml-4 space-y-1">
                <p className="text-sm text-gray-500">• Урок 1</p>
                <p className="text-sm text-gray-500">• Урок 2</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Center: Content editor (Tiptap placeholder) */}
      <div className="col-span-2">
        <Card>
          <CardHeader>
            <CardTitle>{course.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <Input placeholder="Введите заголовок урока..." className="mb-4" />
            <div className="h-64 border rounded flex items-center justify-center text-gray-400">
              Tiptap Editor — скоро
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Right: Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Настройки</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-sm font-medium mb-1">Статус</p>
            <span className="text-sm text-gray-600">{course.status}</span>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" className="w-full">
              Сохранить черновик
            </Button>
            <Button className="w-full">
              Опубликовать
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
