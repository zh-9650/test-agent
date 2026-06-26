import type {
  CaseResult,
  CreateTaskRequest,
  ExecutionRun,
  Task,
  TaskStep,
} from '../types';

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
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ tasks: Task[]; total: number }>;
}

export async function getTask(taskId: number): Promise<Task> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<Task>;
}

export async function getTaskSteps(
  taskId: number,
  runId: string,
  testCaseId?: string,
  attemptNo?: number,
): Promise<{ steps: TaskStep[]; total: number }> {
  const params = new URLSearchParams({ run_id: runId });
  if (testCaseId) params.set('test_case_id', testCaseId);
  if (attemptNo) params.set('attempt_no', String(attemptNo));
  const res = await fetch(`${API_BASE}/tasks/${taskId}/steps?${params}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ steps: TaskStep[]; total: number }>;
}

export async function listTaskRuns(taskId: number): Promise<{ runs: ExecutionRun[]; total: number }> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/runs`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ runs: ExecutionRun[]; total: number }>;
}

export async function getRunResults(taskId: number, runId: string): Promise<{ results: CaseResult[]; total: number }> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/runs/${runId}/results`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ results: CaseResult[]; total: number }>;
}

export function getReportUrl(taskId: number): string {
  return `${API_BASE}/tasks/${taskId}/report`;
}

// Diag log viewer — 9 stage JSON files per task
export interface DiagStageInfo {
  stage: string;
  size: number;
  started_at?: string;
  node?: string;
  status?: string;
}

export interface DiagListResponse {
  task_id: number;
  exists: boolean;
  stages: DiagStageInfo[];
  index: unknown;
}

export async function getDiagList(taskId: number): Promise<DiagListResponse> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/diag`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<DiagListResponse>;
}

export async function getDiagFile(taskId: number, stage: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/diag/${stage}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function stopTask(taskId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/stop`, { method: 'POST' });
  if (!res.ok) throw new Error(await res.text());
}

export async function resumeTask(taskId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/resume`, { method: 'POST' });
  if (!res.ok) throw new Error(await res.text());
}

export async function deleteTask(taskId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await res.text());
}
