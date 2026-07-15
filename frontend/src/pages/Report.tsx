import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  getRunResults,
  getTask,
  getTaskSteps,
  listHumanReviews,
  listTaskRuns,
  resumeTask,
} from '../api/client';
import type { CaseResult, ExecutionRun, HumanReviewRequest, Task, TaskStep } from '../types';

export default function Report() {
  const { taskId } = useParams<{ taskId: string }>();
  const id = Number(taskId);
  const [task, setTask] = useState<Task | null>(null);
  const [runs, setRuns] = useState<ExecutionRun[]>([]);
  const [runId, setRunId] = useState('');
  const [results, setResults] = useState<CaseResult[]>([]);
  const [steps, setSteps] = useState<TaskStep[]>([]);
  const [reviews, setReviews] = useState<HumanReviewRequest[]>([]);
  const [resuming, setResuming] = useState(false);

  useEffect(() => {
    if (!id) return;
    Promise.all([getTask(id), listTaskRuns(id), listHumanReviews(id)]).then(([taskValue, runValue, reviewValue]) => {
      setTask(taskValue);
      setRuns(runValue.runs);
      setReviews(reviewValue.requests);
      setRunId((current) => current || runValue.runs[0]?.run_id || '');
    });
  }, [id]);

  useEffect(() => {
    if (!id || !runId) return;
    Promise.all([getRunResults(id, runId), getTaskSteps(id, runId)]).then(([resultValue, stepValue]) => {
      setResults(resultValue.results);
      setSteps(stepValue.steps);
    });
  }, [id, runId]);

  const selectedRun = runs.find((run) => run.run_id === runId);
  const grouped = useMemo(() => {
    const value = new Map<string, TaskStep[]>();
    for (const step of steps) {
      const key = `${step.test_case_id}:${step.attempt_no}`;
      value.set(key, [...(value.get(key) ?? []), step]);
    }
    return value;
  }, [steps]);

  const primaryErrors = useMemo(() => {
    const value = new Map<string, string>();
    for (const step of steps) {
      if (value.has(step.test_case_id)) continue;
      const status = toolSignal(step, 'status');
      const errorCode = toolSignal(step, 'error_code');
      if (isToolFailureStatus(status) && errorCode) {
        value.set(step.test_case_id, errorCode);
      }
    }
    return value;
  }, [steps]);

  const toolErrorSummary = useMemo(() => {
    const rows = new Map<string, {
      errorCode: string;
      category: string;
      description: string;
      remediation: string;
      count: number;
      caseIds: Set<string>;
    }>();
    for (const step of steps) {
      const status = toolSignal(step, 'status');
      const errorCode = toolSignal(step, 'error_code');
      if (!errorCode || !isToolFailureStatus(status)) continue;
      const taxon = toolErrorTaxon(errorCode);
      const current = rows.get(errorCode) ?? {
        errorCode,
        category: taxon.label,
        description: taxon.description,
        remediation: taxon.remediation,
        count: 0,
        caseIds: new Set<string>(),
      };
      current.count += 1;
      current.caseIds.add(step.test_case_id);
      rows.set(errorCode, current);
    }
    return Array.from(rows.values())
      .map((row) => ({ ...row, caseIds: Array.from(row.caseIds).sort() }))
      .sort((left, right) => right.count - left.count || left.errorCode.localeCompare(right.errorCode));
  }, [steps]);

  const getCaseBadgeClass = (status: string) => {
    switch (status) {
      case 'passed': return 'badge-passed';
      case 'failed': return 'badge-failed';
      case 'incomplete': return 'badge-incomplete';
      case 'skipped': return 'badge-skipped';
      case 'human_review_required': return 'badge-review';
      default: return 'badge-skipped';
    }
  };

  const getCaseStatusLabel = (status: string) => {
    switch (status) {
      case 'passed': return '通过';
      case 'failed': return '失败';
      case 'incomplete': return '未完成';
      case 'skipped': return '跳过';
      case 'human_review_required': return '人工审核';
      default: return status;
    }
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '0 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      
      {/* Header Panel */}
      <header className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ margin: '0 0 0.5rem 0', fontSize: '1.8rem' }}>
            {task?.task_name ?? '运行结果'}
          </h1>
          <p style={{ margin: 0, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
            状态：<span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{task?.status}</span> {' | '}
            报告：<span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{task?.report_status === 'completed' ? '已生成' : '失败/挂起'}</span>
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <Link to={`/monitor/${id}`} className="btn btn-secondary" style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}>
            监控与审查
          </Link>
          <Link to={`/analysis/${id}`} className="btn btn-secondary" style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}>
            分析包详情
          </Link>
        </div>
      </header>

      {/* Select Execution Run */}
      <section className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <label className="form-label" style={{ margin: 0, whiteSpace: 'nowrap' }}>选择运行轮次 (ExecutionRun):</label>
          <select 
            value={runId} 
            onChange={(event) => setRunId(event.target.value)} 
            className="form-select"
            style={{ width: 'auto', minWidth: '320px', padding: '0.5rem 1rem' }}
          >
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.run_id.substring(0, 8)}... ({run.status}) {run.resumed_from_run_id ? '🔄 恢复运行' : '🚀 首次运行'}
              </option>
            ))}
          </select>
        </div>

        {selectedRun && (
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <span className="badge badge-passed">通过 {selectedRun.summary.passed}</span>
            <span className="badge badge-failed">失败 {selectedRun.summary.failed}</span>
            <span className="badge badge-review">人工 {selectedRun.summary.human_review_required}</span>
            <span className="badge badge-incomplete">未完 {selectedRun.summary.incomplete}</span>
            <span className="badge badge-skipped">跳过 {selectedRun.summary.skipped}</span>
          </div>
        )}
      </section>

      {/* Tool Error Summary */}
      <section className="glass-panel">
        <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
          📊 工具执行失败统计 (Tool Error Summary)
        </h2>
        {toolErrorSummary.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', margin: '1rem 0' }}>当前运行未记录工具执行错误。</p>
        ) : (
          <div className="table-container">
            <table className="custom-table">
              <thead>
                <tr>
                  <th style={{ width: '20%' }}>错误码</th>
                  <th style={{ width: '12%' }}>分类</th>
                  <th style={{ width: '8%', textAlign: 'center' }}>次数</th>
                  <th style={{ width: '15%' }}>受影响用例</th>
                  <th style={{ width: '20%' }}>说明</th>
                  <th style={{ width: '25%' }}>修复建议</th>
                </tr>
              </thead>
              <tbody>
                {toolErrorSummary.map((row) => (
                  <tr key={row.errorCode}>
                    <td><code style={{ color: 'var(--color-failed)', fontFamily: 'var(--font-mono)' }}>{row.errorCode}</code></td>
                    <td><span className="badge badge-skipped">{row.category}</span></td>
                    <td style={{ textAlign: 'center', fontWeight: 700 }}>{row.count}</td>
                    <td>{row.caseIds.join(', ')}</td>
                    <td style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{row.description}</td>
                    <td style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>{row.remediation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Human Review History */}
      <section className="glass-panel">
        <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
          👁️ 人工审查历史记录 (Human Review History)
        </h2>
        {reviews.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', margin: '1rem 0' }}>该任务目前无审查记录。</p>
        ) : (
          <div className="table-container">
            <table className="custom-table">
              <thead>
                <tr>
                  <th style={{ width: '8%' }}>ID</th>
                  <th style={{ width: '12%' }}>执行阶段</th>
                  <th style={{ width: '15%' }}>关联用例</th>
                  <th style={{ width: '15%' }}>审核状态</th>
                  <th style={{ width: '50%' }}>审查原因/依据</th>
                </tr>
              </thead>
              <tbody>
                {reviews.map((review) => (
                  <tr key={review.id}>
                    <td>#{review.id}</td>
                    <td><span className="badge badge-skipped">{review.phase}</span></td>
                    <td><code>{review.candidate_case_id || '-'}</code></td>
                    <td>
                      <span className={`badge ${review.status === 'pending' ? 'badge-review' : review.status === 'approved' ? 'badge-passed' : 'badge-failed'}`}>
                        {review.status === 'pending' ? '待审核' : review.status === 'approved' ? '已通过' : '已拒绝'}
                      </span>
                    </td>
                    <td style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem', lineHeight: '1.4' }}>{review.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Memory Provenance - Cleaned Up */}
      <section className="glass-panel">
        <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
          🧠 记忆源头引用 (Memory Provenance)
        </h2>
        {task?.analysis_package?.runtime_hints?.memory_context_refs && task.analysis_package.runtime_hints.memory_context_refs.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem' }}>
            {task.analysis_package.runtime_hints.memory_context_refs.map((ref: { scope_type: string; scope_value: string; memory_key: string; provenance: string }, idx: number) => (
              <div key={idx} className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong style={{ color: 'var(--accent-blue)', fontFamily: 'var(--font-mono)' }}>{ref.memory_key}</strong>
                  <span className="badge badge-skipped" style={{ fontSize: '0.7rem' }}>{ref.scope_type}</span>
                </div>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  目标作用域: <code>{ref.scope_value}</code>
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                  来源依据: {ref.provenance || '无'}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', margin: '0.5rem 0' }}>该任务的分析与规划阶段未引用 Memory 记忆库。</p>
        )}
      </section>

      {/* Detailed Case Results */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <h2 style={{ fontSize: '1.4rem', margin: '0.5rem 0 0' }}>📋 用例执行明细</h2>
        
        {results.map((result) => (
          <div key={result.candidate_case_id} className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            
            {/* Case Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
              <div>
                <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1.2rem', fontFamily: 'var(--font-mono)' }}>
                  {result.candidate_case_id}
                </h3>
                <p style={{ margin: 0, fontSize: '0.95rem', color: 'var(--text-primary)' }}>{result.summary}</p>
              </div>
              <span className={`badge ${getCaseBadgeClass(result.terminal_status)}`} style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem' }}>
                {getCaseStatusLabel(result.terminal_status)}
              </span>
            </div>

            {/* Error Indicators */}
            {result.failure_reason && (
              <div style={{ color: 'var(--color-failed)', fontSize: '0.9rem', padding: '0.5rem 1rem', background: 'var(--bg-failed)', borderRadius: '6px', border: '1px solid rgba(244, 63, 94, 0.15)' }}>
                🚨 失败原因: {result.failure_reason}
              </div>
            )}
            
            {result.terminal_status !== 'passed' && primaryErrors.get(result.candidate_case_id) && (
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                🔍 主要失败工具错误码: <code style={{ color: 'var(--color-failed)', fontFamily: 'var(--font-mono)' }}>{primaryErrors.get(result.candidate_case_id)}</code>
              </div>
            )}

            {/* Attempts details */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '0.5rem' }}>
              {Array.from({ length: result.attempt_count }, (_, index) => index + 1).map((attempt) => (
                <details 
                  key={attempt} 
                  open={attempt === result.attempt_count}
                  className="glass-card"
                  style={{ padding: '0.75rem 1rem' }}
                >
                  <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--text-secondary)', outline: 'none' }}>
                    尝试 (Attempt) #{attempt} {attempt === result.attempt_count ? '(最新)' : ''}
                  </summary>
                  
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.75rem' }}>
                    {(grouped.get(`${result.candidate_case_id}:${attempt}`) ?? []).map((step) => {
                      const status = toolSignal(step, 'status');
                      const errorCode = toolSignal(step, 'error_code');
                      const isFailedStep = isToolFailureStatus(status) || errorCode;

                      return (
                        <div 
                          key={step.id} 
                          style={{ 
                            padding: '0.75rem 1rem', 
                            background: isFailedStep ? 'rgba(244, 63, 94, 0.04)' : 'rgba(255, 255, 255, 0.01)', 
                            border: `1px solid ${isFailedStep ? 'rgba(244, 63, 94, 0.15)' : 'var(--border-color)'}`,
                            borderRadius: '6px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.25rem'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)' }}>
                              #{step.step_index} <span style={{ color: 'var(--accent-blue)', fontFamily: 'var(--font-mono)' }}>{step.action_type}</span> {step.action_target}
                            </div>
                            <span style={{ fontSize: '0.8rem', color: isFailedStep ? 'var(--color-failed)' : 'var(--text-muted)' }}>
                              {isFailedStep ? '❌ 执行失败' : '✔️ 成功'}
                            </span>
                          </div>
                          
                          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', paddingLeft: '1.25rem', borderLeft: '2px solid rgba(255,255,255,0.05)' }}>
                            执行结果: {step.result}
                          </div>

                          {(status || errorCode) && (
                            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem', paddingLeft: '1.25rem', fontSize: '0.75rem' }}>
                              {status && (
                                <span className={`badge ${isToolFailureStatus(status) ? 'badge-failed' : 'badge-passed'}`} style={{ transform: 'scale(0.9)', transformOrigin: 'left' }}>
                                  工具状态: {status}
                                </span>
                              )}
                              {errorCode && (
                                <span className="badge badge-failed" style={{ transform: 'scale(0.9)', transformOrigin: 'left', fontFamily: 'var(--font-mono)' }}>
                                  错误码: {errorCode}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </details>
              ))}
            </div>
          </div>
        ))}
      </section>

      {/* Resume executions */}
      {results.some((result) => result.terminal_status !== 'passed') && task?.status !== 'running' && (
        <div style={{ display: 'flex', justifyContent: 'center', margin: '1.5rem 0 3rem 0' }}>
          <button 
            disabled={resuming}
            onClick={async () => {
              setResuming(true);
              try {
                await resumeTask(id);
                window.location.href = `/monitor/${id}`;
              } finally {
                setResuming(false);
              }
            }} 
            className="btn btn-primary"
            style={{ width: '100%', maxWidth: '400px', padding: '1rem', fontSize: '1.1rem', borderRadius: '10px' }}
          >
            {resuming ? '正在创建恢复队列...' : '🔄 重跑非通过用例 (创建新运行)'}
          </button>
        </div>
      )}
    </div>
  );
}

function toolSignal(step: TaskStep, key: string): string {
  const value = step.change_report?.[key] ?? step.tool_result?.[key];
  return typeof value === 'string' ? value : '';
}

const TOOL_FAILURE_STATUSES = new Set([
  'blocked',
  'failed',
  'timeout',
  'not_found',
  'completion_rejected',
]);

const TOOL_ERROR_TAXONOMY: Record<string, { label: string; description: string; remediation: string }> = {
  policy: {
    label: '策略拦截',
    description: '动作被运行时安全策略或工具准入规则阻止。',
    remediation: '检查动作是否跨域、是否使用限制的容器元素，或是否需要先进入人工审查。',
  },
  selector: {
    label: '元素定位',
    description: '页面元素定位失败、歧义或无法满足唯一性要求。',
    remediation: '优先改用语义编号、可见文本名称或更具体的父级选择器。',
  },
  tool: {
    label: '工具执行',
    description: '浏览器工具调用本身失败、超时或未产生有效操作。',
    remediation: '确认页面加载状态、网络请求是否阻塞，减少不必要的 wait/scroll。',
  },
  case: {
    label: '用例执行',
    description: '用例尝试级别的超时、异常或恢复失败。',
    remediation: '缩小用例目标、补全页面前置环境，或人工接管恢复运行。',
  },
  decision: {
    label: '动作决策',
    description: '大模型决策出的下一步动作缺失、为空或格式不合法。',
    remediation: '检查提示上下文是否缺少当前页面语义、失败反馈或可用工具规范。',
  },
  runtime: {
    label: '运行时兜底',
    description: '运行时遇到的兜底异常或未归类逻辑错误。',
    remediation: '查看底层堆栈、浏览器 Trace 记录并确认 task checkpoint。',
  },
};

const UNKNOWN_TOOL_ERROR = {
  label: '未分类错误',
  description: '未计入标准 taxonomy 的新型工具错误码。',
  remediation: '查看对应步骤的参数配置、元素状态及运行时详细异常后再做归类。',
};

const TOOL_ERROR_CODE_TAXONOMY: Record<string, { label: string; description: string; remediation: string }> = {
  'policy.cross_origin_navigation_blocked': {
    label: '跨域导航被阻止',
    description: 'navigate 目标与任务初始 URL 不同源。',
    remediation: '改用同源路径进行验证；若必须跨系统测试，应配置规则或进入人工作业。',
  },
  'policy.generic_container_selector_blocked': {
    label: '通用容器元素被阻止',
    description: '模型试图操作 body, html 或 document 等容器级大型元素。',
    remediation: '重定位到页面中的具体按钮、输入框、链接或下拉选项。',
  },
  'selector.not_found': {
    label: '页面元素未找到',
    description: '配置的选择器在当前 DOM 中未能匹配到任何实例。',
    remediation: '重新分析当前页面结构，改用更具鲁棒性的编号、文本或可见名称。',
  },
  'selector.ambiguous': {
    label: '元素匹配歧义',
    description: '选择器在页面中匹配到多个元素，定位不唯一导致无法安全操作。',
    remediation: '增加父级定位容器、语义文本说明，或改用精确的 ID/Class 选择器。',
  },
  'tool.timeout': {
    label: '工具调用超时',
    description: 'Playwright 底层操作在指定时效内未完成响应。',
    remediation: '检查网络连接，减少空载 wait 时间，若页面加载极慢可调大超时参数。',
  },
  'tool.missing_select_option_value': {
    label: 'select 选项丢失',
    description: 'select_option 工具未传入明确的 value, label 或 index 参数。',
    remediation: '检查下拉列表包含的子项值，传入合法的 option option_value。',
  },
  'case.attempt_timeout': {
    label: '单次尝试超时',
    description: '该 case 运行尝试总时长超过了最大限制配置。',
    remediation: '适当分割用例目标，或调大 `MAX_CASE_ATTEMPT_SECONDS` 环境变量限制。',
  },
  'case.execution_error': {
    label: '运行期代码异常',
    description: 'case attempt 执行中遭遇严重的 Python 运行时未捕获异常。',
    remediation: '检查底层执行框架、异常堆栈与任务状态，修复代码漏洞后恢复重试。',
  },
  'decision.invalid_or_empty_action': {
    label: '空决策/无效决策',
    description: '大模型未能分析出下一步可行的浏览器操作指令。',
    remediation: '为模型提供更丰富的页面语义信息、动作反馈及下一步方向引导。',
  },
};

function isToolFailureStatus(status: string): boolean {
  return TOOL_FAILURE_STATUSES.has(status);
}

function toolErrorTaxon(errorCode: string): { label: string; description: string; remediation: string } {
  if (TOOL_ERROR_CODE_TAXONOMY[errorCode]) {
    return TOOL_ERROR_CODE_TAXONOMY[errorCode];
  }
  const prefix = errorCode.split('.', 1)[0];
  return TOOL_ERROR_TAXONOMY[prefix] ?? UNKNOWN_TOOL_ERROR;
}
