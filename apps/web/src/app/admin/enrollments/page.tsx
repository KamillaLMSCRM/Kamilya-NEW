'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, Button, Badge, Input, Table } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

interface Course {
  id: string;
  title: string;
  status: string;
}

interface User {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
}

interface Enrollment {
  id: string;
  user_id: string;
  course_id: string;
  status: string;
  enrolled_at: string;
}

export default function EnrollmentsPage() {
  const { t } = useT();
  const [courses, setCourses] = useState<Course[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedCourse, setSelectedCourse] = useState<string>('');
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [enrolling, setEnrolling] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set());
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const [coursesRes, usersRes] = await Promise.all([
        fetch(`${API_URL}/v1/courses`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/v1/users?per_page=100`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (coursesRes.ok) setCourses(await coursesRes.json());
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users || []);
      }
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchEnrollments = async (courseId: string) => {
    setSelectedCourse(courseId);
    setSelectedUsers(new Set());
    if (!token || !courseId) return;
    const res = await fetch(`${API_URL}/v1/courses/${courseId}/enrollments`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) setEnrollments(await res.json());
  };

  const handleEnroll = async () => {
    if (!selectedCourse || selectedUsers.size === 0) return;
    setEnrolling(true);
    try {
      await fetch(`${API_URL}/v1/courses/${selectedCourse}/enrollments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ user_ids: Array.from(selectedUsers) }),
      });
      setSelectedUsers(new Set());
      fetchEnrollments(selectedCourse);
    } finally {
      setEnrolling(false);
    }
  };

  const handleUnenroll = async (enrollmentId: string) => {
    if (!confirm('От записаться пользователя?')) return;
    await fetch(`${API_URL}/v1/courses/enrollments/${enrollmentId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    fetchEnrollments(selectedCourse);
  };

  const toggleUser = (userId: string) => {
    setSelectedUsers((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t('nav.userManagement')} — {t('courses.enrollments')}</h1>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Left: Course selector + enrolled users */}
        <Card>
          <CardContent className="p-4 space-y-4">
            <h2 className="font-semibold">{t('courses.title')}</h2>
            <select
              value={selectedCourse}
              onChange={(e) => fetchEnrollments(e.target.value)}
              className="w-full border rounded-md px-3 py-2 text-sm"
            >
              <option value="">{t('courses.status')}: {t('common.all')}</option>
              {courses.map((c) => (
                <option key={c.id} value={c.id}>{c.title}</option>
              ))}
            </select>

            {selectedCourse && (
              <>
                <h3 className="font-medium text-sm text-gray-500">
                  {t('courses.enrollments')}: {enrollments.length}
                </h3>
                {enrollments.length === 0 ? (
                  <p className="text-sm text-gray-400">{t('courses.noCourses')}</p>
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <th className="text-left p-2">{t('users.name')}</th>
                        <th className="text-left p-2">{t('courses.status')}</th>
                        <th className="text-left p-2">{t('common.delete')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {enrollments.map((e) => {
                        const u = users.find((u) => u.id === e.user_id);
                        return (
                          <tr key={e.id} className="border-t">
                            <td className="p-2">{u ? `${u.first_name} ${u.last_name}` : e.user_id}</td>
                            <td className="p-2">
                              <Badge variant={e.status === 'completed' ? 'default' : 'outline'}>
                                {e.status}
                              </Badge>
                            </td>
                            <td className="p-2">
                              <Button variant="outline" size="sm" onClick={() => handleUnenroll(e.id)}>
                                {t('common.delete')}
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </Table>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Right: Available users to enroll */}
        <Card>
          <CardContent className="p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">{t('nav.userManagement')}</h2>
              <Button
                onClick={handleEnroll}
                disabled={!selectedCourse || selectedUsers.size === 0 || enrolling}
              >
                {enrolling ? t('common.loading') : `${t('courses.enrollments')} (${selectedUsers.size})`}
              </Button>
            </div>
            <p className="text-sm text-gray-500">
              {selectedCourse ? `${t('common.all')}: ${users.length}` : t('courses.status')}
            </p>
            <div className="max-h-96 overflow-y-auto space-y-1">
              {users.map((user) => (
                <label
                  key={user.id}
                  className={`flex items-center gap-3 p-2 rounded cursor-pointer ${
                    selectedUsers.has(user.id) ? 'bg-blue-50' : 'hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedUsers.has(user.id)}
                    onChange={() => toggleUser(user.id)}
                    disabled={!selectedCourse}
                    className="rounded"
                  />
                  <div>
                    <div className="text-sm font-medium">{user.first_name} {user.last_name}</div>
                    <div className="text-xs text-gray-500">{user.email}</div>
                  </div>
                </label>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
