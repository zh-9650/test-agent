export interface RunSummary {
  planned: number;
  terminal: number;
  passed: number;
  failed: number;
  skipped: number;
  incomplete: number;
  human_review_required: number;
}

export interface LatestRun {
  run_id: string;
  status: string;
  summary: RunSummary;
  started_at: string;
  completed_at: string | null;
}

export interface Task {
  id: number;
  task_name: string;
  target_url: string;
  status: string;
  phase: string | null;
  report_status: string;
  failure_reason: string | null;
  config: Record<string, unknown> | null;
  analysis_package: AnalysisPackage | null;
  checkpoints: Record<string, unknown> | null;
  resume_policy: Record<string, unknown> | null;
  latest_run: LatestRun | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ExecutionRun {
  run_id: string;
  task_id: number;
  schema_version: string;
  status: string;
  candidate_case_ids: string[];
  resumed_from_run_id: string | null;
  summary: RunSummary;
  started_at: string;
  completed_at: string | null;
}

export interface CaseResult {
  candidate_case_id: string;
  terminal_status: 'passed' | 'failed' | 'skipped' | 'incomplete' | 'human_review_required';
  attempt_count: number;
  summary: string;
  evidence_refs: string[];
  failure_reason: string | null;
  started_at: string;
  completed_at: string;
}

export interface TaskStep {
  id: number;
  run_id: string;
  test_case_id: string;
  attempt_no: number;
  step_index: number;
  action_type: string;
  action_target: string;
  action_args: Record<string, unknown> | null;
  result: string;
  screenshot_path: string;
  change_report: Record<string, unknown> | null;
  tool_result: Record<string, unknown> | null;
  policy_decision: Record<string, unknown> | null;
  assertion_result: { status: string; reasoning: string } | null;
  created_at: string;
}

export interface HumanReviewRequest {
  id: number;
  task_id: number;
  run_id: string | null;
  candidate_case_id: string;
  phase: string;
  reason: string;
  evidence_refs: string[];
  blocked_tool: string | null;
  requested_at: string;
  status: 'pending' | 'approved' | 'edited' | 'rejected' | string;
}

export interface HumanReviewDecision {
  id: number;
  request_id: number;
  decision: 'approved' | 'edited' | 'rejected' | string;
  edited_inputs: Record<string, unknown> | null;
  approved_tools: string[];
  comment: string | null;
  decided_at: string;
}

export type WSMessageType =
  | 'phase_started'
  | 'phase_completed'
  | 'case_started'
  | 'case_attempt_started'
  | 'case_step'
  | 'case_completed'
  | 'session_completed'
  | 'session_paused_for_review'
  | 'session_failed'
  | 'session_cancelled';

export interface WSMessage {
  type: WSMessageType;
  task_id: number;
  run_id: string;
  phase: string | null;
  candidate_case_id: string;
  attempt_no: number | null;
  step_index: number | null;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface AnalysisPackage {
  facts: Array<{ id: string }>;
  assertions: Array<{ id: string; risk_level: string }>;
  manual_review_items: string[];
  exploration_goals: unknown[];
  system_map: {
    pages: Array<{ title?: string; url_pattern?: string }>;
    actions: Array<{ action_name?: string }>;
    forms: Array<{ form_name?: string }>;
    navigations: Array<Record<string, unknown>>;
  } | null;
  coverage_blueprint: {
    modules: Array<{ id: string; name: string; is_core: boolean }>;
    business_flows: Array<{ id: string; name: string; is_core: boolean }>;
    dependencies: Array<{ id: string; risk_tier: string }>;
    gaps: string[];
  };
  test_conditions: Array<{ id: string; branch_type: string }>;
  coverage_items: Array<{ id: string; branch_type: string }>;
  candidate_cases: Array<{
    id: string;
    title: string;
    module_ids: string[];
    business_flow_ids: string[];
    dependency_ids: string[];
    branch_type: string;
    estimated_cost: string;
  }>;
  traceability_matrix: Record<string, unknown> | null;
  quality_gate_report: {
    passed: boolean;
    findings: Array<{ code: string; severity: 'error' | 'warning'; message: string }>;
  } | null;
  runtime_hints: {
    execution_mode?: 'online' | 'pre_execution' | string;
    execution_skipped?: boolean;
    live_exploration?: {
      status?: string;
      reason?: string;
      target_url?: string;
    };
    memory_context_hint_present?: boolean;
    memory_context_policy?: string;
    memory_context_refs?: Array<{
      scope_type: string;
      scope_value: string;
      memory_key: string;
      source_domain: string;
      provenance: string;
    }>;
    execution_selection?: {
      profile: 'smoke' | 'balanced' | 'full';
      target_count: number | null;
      mandatory_count: number;
      selected_count: number;
      deferred_count: number;
      selected_case_ids: string[];
      deferred_case_ids: string[];
      selection_reasons: Record<string, string[]>;
      coverage_summary: Record<string, unknown>;
    };
  };
}

export interface CreateTaskRequest {
  target_url: string;
  task_name: string;
  config: {
    accounts?: { role: string; username: string; password: string }[];
    rules?: string;
    focus_areas?: string;
    prd?: string;
    swagger?: string;
    tech_doc?: string;
    prototype_url?: string;
    changelog?: string;
    execution_profile?: 'smoke' | 'balanced' | 'full';
    execution_target?: number;
    execution_mode?: 'online' | 'pre_execution';
    prototype_source?: string;
  };
}
