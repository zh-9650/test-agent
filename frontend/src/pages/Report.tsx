import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getTask, getTaskSteps, getReportUrl } from '../api/client';
import type { Task, TaskStep } from '../types';

interface GroupedSteps {
  [testCaseId: string]: TaskStep[];
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
          const status = lastStep?.assertion_result?.status || 'unknown';
          const isExpanded = expanded.has(testCaseId);

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
                  <strong>{testCaseId}</strong>
                  <span style={{ marginLeft: '1rem', fontSize: '0.85rem', color: '#666' }}>
                    {caseSteps.length} 个步骤
                  </span>
                </div>
                <StatusBadge status={status} />
              </div>

              {isExpanded && (
                <div style={{ padding: '1rem', backgroundColor: '#fafafa' }}>
                  {caseSteps.map((step) => (
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
                          Step {step.step_index}: {step.action_type}
                        </strong>
                        <span style={{ fontSize: '0.8rem', color: '#999' }}>
                          {new Date(step.created_at).toLocaleString()}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.85rem', color: '#555', marginBottom: '0.5rem' }}>
                        目标: {step.action_target}
                      </div>
                      {step.assertion_result && (
                        <div
                          style={{
                            padding: '0.5rem',
                            backgroundColor:
                              step.assertion_result.status === 'passed' ? '#f6ffed' : '#fff2f0',
                            borderRadius: '4px',
                            fontSize: '0.85rem',
                          }}
                        >
                          <strong>断言结果:</strong> {step.assertion_result.reasoning}
                        </div>
                      )}
                      {step.screenshot_path && (
                        <div style={{ marginTop: '0.5rem' }}>
                          <a href={step.screenshot_path} target="_blank" rel="noopener noreferrer">
                            查看截图
                          </a>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
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
