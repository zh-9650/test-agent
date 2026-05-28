export interface Task {
  id: number;
  task_name: string;
  target_url: string;
  status: string;
  config: Record<string, unknown> | null;
  test_plan: unknown[] | null;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface TaskStep {
  id: number;
  test_case_id: string;
  step_index: number;
  action_type: string;
  action_target: string;
  action_args: Record<string, unknown> | null;
  result: string;
  screenshot_path: string;
  change_report: Record<string, unknown> | null;
  assertion_result: { status: string; reasoning: string } | null;
  created_at: string;
}

export type WSMessageType =
  | 'page_update'
  | 'ai_thinking'
  | 'action_result'
  | 'assertion_result'
  | 'setup_progress'
  | 'test_case_complete'
  | 'session_complete';

export interface WSMessage {
  type: WSMessageType;
  test_case_id: string;
  step_index: number;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface CreateTaskRequest {
  target_url: string;
  task_name: string;
  config: {
    accounts?: { role: string; username: string; password: string }[];
    rules?: string;
    focus_areas?: string;
  };
}
