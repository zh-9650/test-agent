import type { CreateTaskRequest, Task, TaskStep } from '../types';

const API_BASE = '/api';

export async function createTask(request: CreateTaskRequest): Promise<Task> {
  const res = await fetch(`${API_BASE}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<Task>;
}

export async function listTasks(skip = 0, limit = 20): Promise<{ tasks: Task[]; total: number }> {
  const res = await fetch(`${API_BASE}/tasks?skip=${skip}&limit=${limit}`);
  return res.json() as Promise<{ tasks: Task[]; total: number }>;
}

export async function getTask(taskId: number): Promise<Task> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}`);
  return res.json() as Promise<Task>;
}

export async function getTaskSteps(taskId: number, testCaseId?: string): Promise<{ steps: TaskStep[]; total: number }> {
  const params = testCaseId ? `?test_case_id=${testCaseId}` : '';
  const res = await fetch(`${API_BASE}/tasks/${taskId}/steps${params}`);
  return res.json() as Promise<{ steps: TaskStep[]; total: number }>;
}

export function getReportUrl(taskId: number): string {
  return `${API_BASE}/tasks/${taskId}/report`;
}

export async function stopTask(taskId: number): Promise<void> {
  await fetch(`${API_BASE}/tasks/${taskId}/stop`, { method: 'POST' });
}

export async function deleteTask(taskId: number): Promise<void> {
  await fetch(`${API_BASE}/tasks/${taskId}`, { method: 'DELETE' });
}
