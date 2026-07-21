'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login: string | null;
}

interface NewUserForm {
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  password: string;
}

const createEmptyNewUser = (): NewUserForm => ({
  email: '',
  first_name: '',
  last_name: '',
  role: 'methodologist',
  password: '',
});

export default function AdminTeamPage() {
  const { t } = useT();
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  // ADR-0011: team surface starts with methodologist, not student.
  // Student provisioning goes through /admin/staff (Excel import) or the
  // Telegram-bot flow. Platform superadmin is tenant_id=NULL and must
  // never be created from this tenant-level surface.
  const [newUser, setNewUser] = useState<NewUserForm>(createEmptyNewUser);
  const [createFormKey, setCreateFormKey] = useState(0);
  const [createFormUnlocked, setCreateFormUnlocked] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchUsers = useCallback(async () => {
    if (!token) return;
    const params = new URLSearchParams({
      page: String(page),
      per_page: '20',
    });
    if (search) params.set('search', search);
    try {
      const res = await fetch(`${API_URL}/v1/users?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setUsers(data.users || []);
        setTotal(data.total || 0);
      }
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, page, search]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const [createError, setCreateError] = useState('');

  const openCreateModal = () => {
    setCreateError('');
    setNewUser(createEmptyNewUser());
    setCreateFormUnlocked(false);
    setCreateFormKey((key) => key + 1);
    setShowCreateModal(true);
  };

  const handleCreateModalOpenChange = (open: boolean) => {
    setShowCreateModal(open);
    if (open) {
      setCreateError('');
      setNewUser(createEmptyNewUser());
      setCreateFormUnlocked(false);
      setCreateFormKey((key) => key + 1);
    }
  };

  const getCreateErrorMessage = (payload: unknown, status: number) => {
    const response = payload && typeof payload === 'object'
      ? payload as { detail?: unknown; message?: unknown }
      : {};
    const detail = response.detail;

    if (typeof detail === 'string') {
      if (detail === 'Email already exists') {
        return t('users.teamPage.errors.emailExists');
      }
      return detail;
    }

    if (Array.isArray(detail)) {
      const validationMessage = detail
        .map((item) => item && typeof item === 'object' && 'msg' in item ? String(item.msg) : '')
        .filter(Boolean)
        .join('; ');
      if (validationMessage) return validationMessage;
    }

    if (detail && typeof detail === 'object') {
      const structured = detail as { code?: string; current?: number; limit?: number; message?: string };
      if (structured.code === 'trial_limit_exceeded' || structured.code === 'demo_limit_exceeded') {
        if (typeof structured.current === 'number' && typeof structured.limit === 'number') {
          return t('users.teamPage.errors.limitReached', {
            current: structured.current,
            limit: structured.limit,
          });
        }
        return structured.message || t('users.teamPage.errors.limitExceeded');
      }
      if (structured.message) return structured.message;
    }

    if (typeof response.message === 'string') return response.message;
    if (status === 403) return t('users.teamPage.errors.forbidden');
    return t('users.teamPage.errors.generic');
  };

  const handleCreate = async () => {
    if (isCreating) return;
    setCreateError('');
    if (!newUser.email.trim()) { setCreateError(t('users.teamPage.errors.emailRequired')); return; }
    if (!newUser.first_name.trim()) { setCreateError(t('users.teamPage.errors.firstNameRequired')); return; }
    if (!newUser.last_name.trim()) { setCreateError(t('users.teamPage.errors.lastNameRequired')); return; }
    if (newUser.password.length < 8) { setCreateError(t('users.teamPage.errors.passwordMin')); return; }

    setIsCreating(true);
    try {
      const res = await fetch(`${API_URL}/v1/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          ...newUser,
          email: newUser.email.trim().toLowerCase(),
          first_name: newUser.first_name.trim(),
          last_name: newUser.last_name.trim(),
        }),
      });
      if (res.ok) {
        setShowCreateModal(false);
        setNewUser(createEmptyNewUser());
        await fetchUsers();
      } else {
        const err: unknown = await res.json().catch(() => null);
        setCreateError(getCreateErrorMessage(err, res.status));
      }
    } catch {
      setCreateError(t('users.teamPage.errors.network'));
    } finally {
      setIsCreating(false);
    }
  };

  const handleToggleActive = async (userId: string, currentActive: boolean) => {
    const method = currentActive ? 'DELETE' : 'PATCH';
    const res = await fetch(`${API_URL}/v1/users/${userId}`, {
      method,
      headers: { Authorization: `Bearer ${token}` },
      ...(method === 'PATCH' ? { body: JSON.stringify({ is_active: true }), headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } } : {}),
    });
    if (res.ok) fetchUsers();
  };

  const handleChangeRole = async (userId: string, newRole: string) => {
    const res = await fetch(`${API_URL}/v1/users/${userId}/role?role=${newRole}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) fetchUsers();
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t('users.teamPage.title')}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t('users.teamPage.subtitle')}
          </p>
        </div>
        <Button onClick={openCreateModal}>+ {t('users.createButton')}</Button>
      </div>

      <div className="flex gap-2">
        <label htmlFor="users-search" className="sr-only">
          {t('users.searchPlaceholder')}
        </label>
        <Input
          id="users-search"
          placeholder={t('users.searchPlaceholder')}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="max-w-sm"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 text-muted-foreground">{t('users.loadingList')}</div>
          ) : users.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground">{t('users.noUsersFound')}</div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th scope="col" className="text-left p-3">{t('users.name')}</th>
                  <th scope="col" className="text-left p-3">{t('users.email')}</th>
                  <th scope="col" className="text-left p-3">{t('users.role')}</th>
                  <th scope="col" className="text-left p-3">{t('users.status')}</th>
                  <th scope="col" className="text-left p-3">{t('users.created')}</th>
                  <th scope="col" className="text-right p-3">{t('users.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id} className="border-t">
                    <td className="p-3 font-medium">
                      {user.first_name} {user.last_name}
                    </td>
                    <td className="p-3 text-muted-foreground">{user.email}</td>
                    <td className="p-3">
                      <label htmlFor={`role-${user.id}`} className="sr-only">
                        {t('users.changeRole')}
                      </label>
                      <select
                        id={`role-${user.id}`}
                        value={user.role}
                        onChange={(e) => handleChangeRole(user.id, e.target.value)}
                        className="border rounded px-2 py-1 text-sm bg-card"
                      >
                        {/* ADR-0011: only team-managed roles. Students are provisioned via
                            Telegram-bot or /admin/staff import and never appear here. */}
                        <option value="methodologist">{t('users.roleMethodologist')}</option>
                        <option value="org_admin">{t('users.roleOrgAdmin')}</option>
                        <option value="admin">{t('users.roleAdmin')}</option>
                      </select>
                    </td>
                    <td className="p-3">
                      <Badge variant={user.is_active ? 'default' : 'destructive'}>
                        {user.is_active ? t('users.active') : t('users.blocked')}
                      </Badge>
                    </td>
                    <td className="p-3 text-muted-foreground text-sm">
                      {new Date(user.created_at).toLocaleDateString(undefined)}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        type="button"
                        onClick={() => handleToggleActive(user.id, user.is_active)}
                        className={`text-sm hover:underline ${
                          user.is_active ? 'text-destructive' : 'text-success'
                        }`}
                      >
                        {user.is_active ? t('users.block') : t('users.unblock')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-between items-center">
        <span className="text-sm text-muted-foreground">
          {t('users.totalCount', { total })}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            {t('users.prevPage')}
          </Button>
          <span className="text-sm py-2 px-3 text-foreground">
            {t('users.page', { page })}
          </span>
          <Button
            variant="outline"
            onClick={() => setPage((p) => p + 1)}
            disabled={users.length < 20}
          >
            {t('users.nextPage')}
          </Button>
        </div>
      </div>

      {/* Create user modal */}
      <Modal open={showCreateModal} onOpenChange={handleCreateModalOpenChange}>
        <CardHeader>
          <CardTitle>{t('users.teamPage.newMember')}</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            key={createFormKey}
            className="space-y-4"
            autoComplete="off"
            data-form-type="other"
            onSubmit={(event) => {
              event.preventDefault();
              void handleCreate();
            }}
          >
          <div className="sr-only" aria-hidden="true">
            <input type="text" name="username" autoComplete="username" tabIndex={-1} />
            <input type="password" name="password" autoComplete="current-password" tabIndex={-1} />
          </div>
          <label className="block">
            <span className="text-sm text-foreground mb-1 block">{t('users.email')}</span>
            <Input
              name={`team_member_email_${createFormKey}`}
              type="email"
              autoComplete="off"
              data-lpignore="true"
              data-1p-ignore="true"
              data-form-type="other"
              readOnly={!createFormUnlocked}
              onFocus={() => setCreateFormUnlocked(true)}
              value={newUser.email}
              onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-sm text-foreground mb-1 block">{t('users.name')}</span>
            <Input
              name={`team_member_first_name_${createFormKey}`}
              autoComplete="off"
              data-lpignore="true"
              data-1p-ignore="true"
              readOnly={!createFormUnlocked}
              onFocus={() => setCreateFormUnlocked(true)}
              value={newUser.first_name}
              onChange={(e) => setNewUser({ ...newUser, first_name: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-sm text-foreground mb-1 block">{t('users.surname')}</span>
            <Input
              name={`team_member_last_name_${createFormKey}`}
              autoComplete="off"
              data-lpignore="true"
              data-1p-ignore="true"
              readOnly={!createFormUnlocked}
              onFocus={() => setCreateFormUnlocked(true)}
              value={newUser.last_name}
              onChange={(e) => setNewUser({ ...newUser, last_name: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-sm text-foreground mb-1 block">{t('users.role')}</span>
            <select
              value={newUser.role}
              onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card"
            >
              {/* ADR-0011: students are not team-managed. Backend will 400
                  if 'student' is sent here. */}
              <option value="methodologist">{t('users.roleMethodologist')}</option>
              <option value="org_admin">{t('users.roleOrgAdmin')}</option>
              <option value="admin">{t('users.roleAdmin')}</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm text-foreground mb-1 block">{t('users.password')}</span>
            <Input
              name={`team_member_password_${createFormKey}`}
              type="password"
              autoComplete="new-password"
              data-lpignore="true"
              data-1p-ignore="true"
              data-form-type="other"
              readOnly={!createFormUnlocked}
              onFocus={() => setCreateFormUnlocked(true)}
              value={newUser.password}
              onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
            />
          </label>
          {createError && <p className="text-sm text-destructive">{createError}</p>}
          <Button type="submit" className="w-full" disabled={isCreating}>
            {isCreating ? t('users.teamPage.creating') : t('users.createButton')}
          </Button>
          </form>
        </CardContent>
      </Modal>

    </div>
  );
}
