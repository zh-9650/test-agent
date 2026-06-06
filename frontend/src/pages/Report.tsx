import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getTask, getTaskSteps, getReportUrl, getDiagList, getDiagFile } from '../api/client';
import type { DiagStageInfo } from '../api/client';
import type { Task, TaskStep } from '../types';

interface GroupedSteps {
  [testCaseId: string]: TaskStep[];
}

interface TestPlanEntry {
  id?: string;
  title?: string;
  steps?: unknown[];
}

interface DiagPanelState {
  exists: boolean;
  stages: DiagStageInfo[];
  index: unknown;
}

/**
 * Normalize assertion status from backend format to frontend format.
 * Backend stores: 'pass' / 'fail'
 * Frontend expects: 'passed' / 'failed'
 */
function normalizeStatus(status: string | undefined): string {
  if (!status) return 'unknown';
  const lower = status.toLowerCase();
  if (lower === 'pass' || lower === 'passed') return 'passed';
  if (lower === 'fail' || lower === 'failed') return 'failed';
  return lower;
}

/**
 * Convert a screenshot path to a displayable URL.
 * - If it's a base64 data URL, return as-is for direct <img> use.
 * - If it's a file path, extract the filename and return an HTTP URL
 *   pointing to the backend's static file endpoint.
 */
function getScreenshotUrl(screenshotPath: string): { url: string; isBase64: boolean } {
  if (!screenshotPath) return { url: '', isBase64: false };
  // Base64 data URL
  if (screenshotPath.startsWith('data:')) {
    return { url: screenshotPath, isBase64: true };
  }
  // File path — extract filename and use backend static endpoint
  const parts = screenshotPath.replace(/\\/g, '/').split('/');
  const filename = parts[parts.length - 1];
  return { url: `/static/screenshots/${filename}`, isBase64: false };
}

export default function Report() {
  const { taskId } = useParams<{ taskId: string }>();
  const numericTaskId = taskId ? parseInt(taskId, 10) : 0;
  const [task, setTask] = useState<Task | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [_steps, setSteps] = useState<TaskStep[]>([]);
  const [grouped, setGrouped] = useState<GroupedSteps>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'report' | 'diag'>('report');

  useEffect(() => {
    if (!numericTaskId) return;

    const fetchData = async () => {
      try {
        const [taskRes, stepsRes] = await Promise.all([
          getTask(numericTaskId),
          getTaskSteps(numericTaskId),
        ]);
        setTask(taskRes);
        setSteps(stepsRes.steps);

        const g: GroupedSteps = {};
        for (const step of stepsRes.steps) {
          if (!g[step.test_case_id]) g[step.test_case_id] = [];
          g[step.test_case_id].push(step);
        }
        for (const k of Object.keys(g)) {
          g[k].sort((a, b) => a.step_index - b.step_index);
        }
        setGrouped(g);
      } catch (err) {
        console.error('Failed to load report:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [numericTaskId]);

  const toggleExpand = (testCaseId: string) => {
    const next = new Set(expanded);
    if (next.has(testCaseId)) {
      next.delete(testCaseId);
    } else {
      next.add(testCaseId);
    }
    setExpanded(next);
  };

  if (loading) {
    return <div style={{ padding: '2rem' }}>加载中...</div>;
  }

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '2rem 1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h1 style={{ margin: 0 }}>测试报告</h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <a
            href={getReportUrl(numericTaskId)}
            download
            style={{
              padding: '0.5rem 1rem',
              backgroundColor: '#1890ff',
              color: '#fff',
              textDecoration: 'none',
              borderRadius: '4px',
              fontWeight: 600,
            }}
          >
            下载报告
          </a>
          <Link
            to="/history"
            style={{
              padding: '0.5rem 1rem',
              backgroundColor: '#f0f0f0',
              color: '#333',
              textDecoration: 'none',
              borderRadius: '4px',
              fontWeight: 600,
            }}
          >
            返回历史
          </Link>
        </div>
      </div>

      {/* Tabs: 测试报告 | 诊断日志 */}
      <div style={{ display: 'flex', gap: '0', borderBottom: '2px solid #f0f0f0', marginBottom: '1.5rem' }}>
        <TabButton label="测试报告" active={activeTab === 'report'} onClick={() => setActiveTab('report')} />
        <TabButton label="诊断日志" active={activeTab === 'diag'} onClick={() => setActiveTab('diag')} />
      </div>

      {activeTab === 'report' && (
        <>
      {/* Summary Stats */}
      {task && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
            gap: '1rem',
            marginBottom: '2rem',
          }}
        >
          <StatCard label="总用例" value={task.total_tests} color="#1890ff" />
          <StatCard label="通过" value={task.passed_tests} color="#52c41a" />
          <StatCard label="失败" value={task.failed_tests} color="#ff4d4f" />
          <StatCard
            label="成功率"
            value={
              task.total_tests > 0
                ? `${Math.round((task.passed_tests / task.total_tests) * 100)}%`
                : '0%'
            }
            color="#fa8c16"
          />
        </div>
      )}

      {/* Per Test Case Cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {Object.entries(grouped).map(([testCaseId, caseSteps]) => {
          const lastStep = caseSteps[caseSteps.length - 1];
          const status = normalizeStatus(lastStep?.assertion_result?.status);
          const isExpanded = expanded.has(testCaseId);
          
          // Try to find the corresponding test case in the test plan to get semantic steps
          let testCaseInfo: TestPlanEntry | undefined;
          if (task?.test_plan && Array.isArray(task.test_plan)) {
            testCaseInfo = task.test_plan.find((entry): entry is TestPlanEntry => (
              typeof entry === 'object'
              && entry !== null
              && 'id' in entry
              && (entry as TestPlanEntry).id === testCaseId
            ));
          }

          return (
            <div
              key={testCaseId}
              style={{
                border: '1px solid #ddd',
                borderRadius: '6px',
                overflow: 'hidden',
                backgroundColor: '#fff',
              }}
            >
              <div
                onClick={() => toggleExpand(testCaseId)}
                style={{
                  padding: '1rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  cursor: 'pointer',
                  backgroundColor: status === 'passed' ? '#f6ffed' : status === 'failed' ? '#fff2f0' : '#fafafa',
                  borderLeft: `4px solid ${
                    status === 'passed' ? '#52c41a' : status === 'failed' ? '#ff4d4f' : '#d9d9d9'
                  }`,
                }}
              >
                <div>
                  <strong>{testCaseId} {testCaseInfo?.title ? `- ${testCaseInfo.title}` : ''}</strong>
                  <span style={{ marginLeft: '1rem', fontSize: '0.85rem', color: '#666' }}>
                    {caseSteps.length} 个步骤
                  </span>
                </div>
                <StatusBadge status={status} />
              </div>

              {isExpanded && (
                <div style={{ padding: '1rem', backgroundColor: '#fafafa' }}>
                  {caseSteps.map((step) => {
                    const semanticStep = testCaseInfo?.steps?.[step.step_index];
                    return (
                    <div
                      key={step.id}
                      style={{
                        marginBottom: '0.75rem',
                        padding: '0.75rem',
                        backgroundColor: '#fff',
                        border: '1px solid #eee',
                        borderRadius: '4px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                        <strong>
                          Step {step.step_index + 1}: {semanticStep ? `${semanticStep} (${step.action_type})` : step.action_type}
                        </strong>
                        <span style={{ fontSize: '0.8rem', color: '#999' }}>
                          {new Date(step.created_at).toLocaleString()}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.85rem', color: '#555', marginBottom: '0.5rem' }}>
                        <strong>参数:</strong> {Object.keys(step.action_args || {}).length > 0 
                          ? JSON.stringify(step.action_args) 
                          : '无参数'}
                      </div>
                      {step.assertion_result && (
                        <div
                          style={{
                            padding: '0.5rem',
                            backgroundColor:
                              normalizeStatus(step.assertion_result.status) === 'passed' ? '#f6ffed' : '#fff2f0',
                            borderRadius: '4px',
                            fontSize: '0.85rem',
                          }}
                        >
                          <strong>断言结果:</strong> {step.assertion_result.reasoning}
                        </div>
                      )}
                      {step.screenshot_path && (
                        <div style={{ marginTop: '0.5rem' }}>
                          {(() => {
                            const { url, isBase64 } = getScreenshotUrl(step.screenshot_path);
                            if (!url) return null;
                            if (isBase64) {
                              return (
                                <img
                                  src={url}
                                  alt="截图"
                                  style={{ maxWidth: '100%', maxHeight: '300px', borderRadius: '4px', cursor: 'pointer' }}
                                  onClick={() => window.open(url, '_blank')}
                                />
                              );
                            }
                            return (
                              <a href={url} target="_blank" rel="noopener noreferrer">
                                查看截图
                              </a>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
        </>
      )}

      {activeTab === 'diag' && <DiagPanel taskId={numericTaskId} />}
    </div>
  );
}

// ============================================================================
// DiagPanel: 树状展示 9 stage JSON 诊断日志
// ============================================================================
function DiagPanel({ taskId }: { taskId: number }) {
  const [list, setList] = useState<DiagPanelState | null>(null);
  const [activeStage, setActiveStage] = useState<string | null>(null);
  const [content, setContent] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getDiagList(taskId)
      .then((d) => {
        if (!mounted) return;
        setList({ exists: d.exists, stages: d.stages, index: d.index });
        setLoading(false);
        if (d.stages.length > 0) {
          setActiveStage((current) => current ?? d.stages[0].stage);
        }
      })
      .catch((e) => {
        if (!mounted) return;
        setError(String(e));
        setLoading(false);
      });
    return () => { mounted = false; };
  }, [taskId]);

  useEffect(() => {
    if (!activeStage) return;
    let mounted = true;
    getDiagFile(taskId, activeStage)
      .then((d) => { if (mounted) setContent(d); })
      .catch((e) => { if (mounted) setError(String(e)); });
    return () => { mounted = false; };
  }, [activeStage, taskId]);

  if (loading) return <div style={{ padding: '1rem' }}>加载诊断日志…</div>;
  if (error) return <div style={{ padding: '1rem', color: '#ff4d4f' }}>加载失败: {error}</div>;
  if (!list || !list.exists) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: '#999', background: '#fafafa', borderRadius: '6px' }}>
        该任务尚无诊断日志 (DIAG_ENABLED=false 或 task 未开始)
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '1rem' }}>
      {/* 左侧: 9 stage 列表 */}
      <div style={{ background: '#fff', border: '1px solid #eee', borderRadius: '6px', padding: '0.5rem' }}>
        <div style={{ fontSize: '0.85rem', color: '#666', padding: '0.5rem', borderBottom: '1px solid #eee' }}>
          {list.stages.length} 个阶段日志
        </div>
        {list.stages.map((s) => (
          <div
            key={s.stage}
            onClick={() => setActiveStage(s.stage)}
            style={{
              padding: '0.6rem 0.75rem',
              cursor: 'pointer',
              borderRadius: '4px',
              marginBottom: '0.25rem',
              backgroundColor: activeStage === s.stage ? '#e6f7ff' : 'transparent',
              borderLeft: `3px solid ${activeStage === s.stage ? '#1890ff' : 'transparent'}`,
            }}
          >
            <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{s.stage}</div>
            <div style={{ fontSize: '0.75rem', color: '#999', marginTop: '0.15rem' }}>
              {s.node && <span style={{ marginRight: '0.5rem' }}>node: {s.node}</span>}
              {s.status && <span style={{ marginRight: '0.5rem' }}>status: {s.status}</span>}
              {s.size && <span>{s.size}B</span>}
            </div>
          </div>
        ))}
      </div>

      {/* 右侧: 选中 stage 的 JSON 内容 */}
      <div style={{ background: '#fafafa', border: '1px solid #eee', borderRadius: '6px', padding: '1rem' }}>
        {content ? <JsonTree data={content} /> : <div style={{ color: '#999' }}>选择左侧阶段查看详情</div>}
      </div>
    </div>
  );
}

// 简易 JSON 树 (嵌套对象可展开)
function JsonTree({ data }: { data: unknown }) {
  return (
    <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: '0.85rem' }}>
      <JsonNode value={data} keyName="(root)" depth={0} />
    </div>
  );
}

function JsonNode({ value, keyName, depth }: { value: unknown; keyName: string; depth: number }) {
  const [open, setOpen] = useState(true);
  const pad = depth * 16;
  if (value === null) {
    return <div style={{ paddingLeft: pad }}><span style={{ color: '#888' }}>{keyName}:</span> <span style={{ color: '#d4380d' }}>null</span></div>;
  }
  if (typeof value === 'string') {
    const display = value.length > 200 ? value.slice(0, 200) + `…(共${value.length}字)` : value;
    return (
      <div style={{ paddingLeft: pad, wordBreak: 'break-all' }}>
        <span style={{ color: '#888' }}>{keyName}:</span> <span style={{ color: '#096dd9' }}>"{display}"</span>
      </div>
    );
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return <div style={{ paddingLeft: pad }}><span style={{ color: '#888' }}>{keyName}:</span> <span style={{ color: '#d4380d' }}>{String(value)}</span></div>;
  }
  if (Array.isArray(value)) {
    return (
      <div style={{ paddingLeft: pad }}>
        <span style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => setOpen(!open)}>
          {open ? '▼' : '▶'} <span style={{ color: '#888' }}>{keyName}:</span> <span style={{ color: '#666' }}>[{value.length}]</span>
        </span>
        {open && value.map((v, i) => <JsonNode key={i} value={v} keyName={`[${i}]`} depth={depth + 1} />)}
      </div>
    );
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record);
    return (
      <div style={{ paddingLeft: pad }}>
        <span style={{ cursor: 'pointer', userSelect: 'none' }} onClick={() => setOpen(!open)}>
          {open ? '▼' : '▶'} <span style={{ color: '#888' }}>{keyName}:</span> <span style={{ color: '#666' }}>{`{${keys.length}}`}</span>
        </span>
        {open && keys.map((k) => <JsonNode key={k} value={record[k]} keyName={k} depth={depth + 1} />)}
      </div>
    );
  }
  return <div style={{ paddingLeft: pad }}>{String(value)}</div>;
}

// ============================================================================
// TabButton / StatCard / StatusBadge (原文件保留)
// ============================================================================
function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '0.6rem 1.5rem',
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        fontSize: '1rem',
        fontWeight: active ? 700 : 500,
        color: active ? '#1890ff' : '#666',
        borderBottom: active ? '2px solid #1890ff' : '2px solid transparent',
        marginBottom: '-2px',
      }}
    >
      {label}
    </button>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div
      style={{
        padding: '1rem',
        borderRadius: '6px',
        backgroundColor: '#fff',
        border: `1px solid ${color}22`,
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: '0.85rem', color: '#666', marginBottom: '0.25rem' }}>{label}</div>
      <div style={{ fontSize: '1.5rem', fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    passed: '#52c41a',
    failed: '#ff4d4f',
    unknown: '#d9d9d9',
  };

  return (
    <span
      style={{
        padding: '0.25rem 0.75rem',
        borderRadius: '4px',
        backgroundColor: colors[status] || colors.unknown,
        color: '#fff',
        fontSize: '0.8rem',
        fontWeight: 600,
      }}
    >
      {status.toUpperCase()}
    </span>
  );
}
