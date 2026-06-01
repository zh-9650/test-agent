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
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ tasks: Task[]; total: number }>;
}

export async function getTask(taskId: number): Promise<Task> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<Task>;
}

export async function getTaskSteps(taskId: number, testCaseId?: string): Promise<{ steps: TaskStep[]; total: number }> {
  const params = testCaseId ? `?test_case_id=${testCaseId}` : '';
  const res = await fetch(`${API_BASE}/tasks/${taskId}/steps${params}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ steps: TaskStep[]; total: number }>;
}

export function getReportUrl(taskId: number): string {
  return `${API_BASE}/tasks/${taskId}/report`;
}

export async function stopTask(taskId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}/stop`, { method: 'POST' });
  if (!res.ok) throw new Error(await res.text());
}

export async function deleteTask(taskId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await res.text());
}

export async function testLayer1(
  prd: string, 
  apiDoc: string, 
  changelog: string,
  onProgress?: (msg: string) => void
): Promise<any> {
  const res = await fetch(`${API_BASE}/test/layer1`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prd, api_doc: apiDoc, changelog }),
  });
  if (!res.ok) throw new Error(await res.text());
  
  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");
  
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult = null;
  
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const data = JSON.parse(line);
        if (data.progress === 'error') {
          throw new Error(data.error || 'Layer 1 pipeline failed');
        } else if (data.progress && data.progress !== 'done') {
          if (onProgress) onProgress(data.progress);
        } else if (data.progress === 'done') {
          finalResult = data;
        }
      } catch (e) {
        // ignore parse error
      }
    }
  }

  return finalResult;
}
