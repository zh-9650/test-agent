import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getTask } from '../api/client';
import type { Task } from '../types';

export default function AnalysisPackagePage() {
  const { taskId } = useParams<{ taskId: string }>();
  const numericTaskId = taskId ? parseInt(taskId, 10) : 0;
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!numericTaskId) return;
    getTask(numericTaskId)
      .then(setTask)
      .catch((err) => {
        console.error('Failed to fetch task:', err);
        setError('加载任务失败');
      })
      .finally(() => setLoading(false));
  }, [numericTaskId]);

  if (loading) {
    return <div style={{ padding: '2rem' }}>加载中...</div>;
  }

  if (error) {
    return <div style={{ padding: '2rem', color: '#ff4d4f' }}>{error}</div>;
  }

  if (!task) {
    return <div style={{ padding: '2rem' }}>任务不存在</div>;
  }

  const pkg = task.analysis_package;
  const selection = pkg?.runtime_hints?.execution_selection;
  const findings = pkg?.quality_gate_report?.findings || [];
  const errors = findings.filter((item) => item.severity === 'error');
  const warnings = findings.filter((item) => item.severity === 'warning');
  const branchCounts = (pkg?.candidate_cases || []).reduce<Record<string, number>>((counts, item) => {
    counts[item.branch_type] = (counts[item.branch_type] || 0) + 1;
    return counts;
  }, {});

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '2rem 1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <h1 style={{ margin: 0 }}>分析包详情</h1>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Link
            to={`/report/${task.id}`}
            style={{
              padding: '0.5rem 1rem',
              backgroundColor: '#1890ff',
              color: '#fff',
              textDecoration: 'none',
              borderRadius: '4px',
              fontWeight: 600,
            }}
          >
            查看报告
          </Link>
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

      {/* 任务基本信息 */}
      <div style={{ marginBottom: '2rem', padding: '1rem', backgroundColor: '#f5f5f5', borderRadius: '6px' }}>
        <h3 style={{ marginTop: 0 }}>任务信息</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
          <div><strong>任务名称:</strong> {task.task_name}</div>
          <div><strong>目标 URL:</strong> {task.target_url}</div>
          <div><strong>状态:</strong> {task.status}</div>
          <div><strong>创建时间:</strong> {new Date(task.created_at).toLocaleString()}</div>
        </div>
      </div>

      {/* 分析包摘要 */}
      {pkg ? (
        <>
          <div style={{ marginBottom: '2rem' }}>
            <h3>分析包摘要</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
              <StatCard label="事实数量" value={pkg.facts?.length || 0} color="#1890ff" />
              <StatCard label="断言数量" value={pkg.assertions?.length || 0} color="#52c41a" />
              <StatCard label="人工审核项" value={pkg.manual_review_items?.length || 0} color="#fa8c16" />
              <StatCard label="探索目标" value={pkg.exploration_goals?.length || 0} color="#722ed1" />
              <StatCard label="候选用例" value={pkg.candidate_cases?.length || 0} color="#eb2f96" />
              <StatCard label="实际选中" value={selection?.selected_count || 0} color="#13c2c2" />
              <StatCard label="延后资产" value={selection?.deferred_count || 0} color="#8c8c8c" />
              <StatCard label="系统地图" value={pkg.system_map ? '存在' : '不存在'} color={pkg.system_map ? '#52c41a' : '#ff4d4f'} />
            </div>
          </div>

          {selection && (
            <div style={{ marginBottom: '2rem' }}>
              <h3>执行集选择</h3>
              <p>
                策略 <strong>{selection.profile}</strong>，目标 {selection.target_count ?? '全部'}，
                必选 {selection.mandatory_count}，选中 {selection.selected_count}，延后 {selection.deferred_count}。
              </p>
              <pre style={{ padding: '1rem', background: '#fafafa', overflow: 'auto' }}>
                {JSON.stringify(selection.selection_reasons, null, 2)}
              </pre>
            </div>
          )}

          <div style={{ marginBottom: '2rem' }}>
            <h3>覆盖分布</h3>
            <p>
              模块 {pkg.coverage_blueprint?.modules?.length || 0}，
              流程 {pkg.coverage_blueprint?.business_flows?.length || 0}，
              依赖 {pkg.coverage_blueprint?.dependencies?.length || 0}
            </p>
            <pre style={{ padding: '1rem', background: '#fafafa' }}>
              {JSON.stringify(branchCounts, null, 2)}
            </pre>
          </div>

          {findings.length > 0 && (
            <div style={{ marginBottom: '2rem' }}>
              <h3>质量门</h3>
              <h4 style={{ color: '#cf1322' }}>错误 ({errors.length})</h4>
              <ul>{errors.map((item, index) => <li key={`${item.code}-${index}`}>{item.message}</li>)}</ul>
              <h4 style={{ color: '#d46b08' }}>警告 ({warnings.length})</h4>
              <ul>{warnings.map((item, index) => <li key={`${item.code}-${index}`}>{item.message}</li>)}</ul>
            </div>
          )}

          {/* 系统地图详情 */}
          {pkg.system_map && (
            <div style={{ marginBottom: '2rem' }}>
              <h3>系统地图</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
                <div>
                  <h4>页面 ({pkg.system_map.pages?.length || 0})</h4>
                  <ul style={{ maxHeight: '200px', overflowY: 'auto' }}>
                    {pkg.system_map.pages?.map((page, i) => (
                      <li key={i}>{page.title || page.url_pattern || `页面 ${i + 1}`}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h4>操作 ({pkg.system_map.actions?.length || 0})</h4>
                  <ul style={{ maxHeight: '200px', overflowY: 'auto' }}>
                    {pkg.system_map.actions?.map((action, i) => (
                      <li key={i}>{action.action_name || `操作 ${i + 1}`}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h4>表单 ({pkg.system_map.forms?.length || 0})</h4>
                  <ul style={{ maxHeight: '200px', overflowY: 'auto' }}>
                    {pkg.system_map.forms?.map((form, i) => (
                      <li key={i}>{form.form_name || `表单 ${i + 1}`}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* 人工审核项 */}
          {pkg.manual_review_items && pkg.manual_review_items.length > 0 && (
            <div style={{ marginBottom: '2rem' }}>
              <h3>人工审核项</h3>
              <ul>
                {pkg.manual_review_items.map((item, i) => (
                  <li key={i} style={{ marginBottom: '0.5rem', padding: '0.5rem', backgroundColor: '#fff2f0', borderRadius: '4px' }}>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 原始 JSON */}
          <div style={{ marginBottom: '2rem' }}>
            <h3>原始分析包 (JSON)</h3>
            <details>
              <summary style={{ cursor: 'pointer', padding: '0.5rem', backgroundColor: '#f5f5f5', borderRadius: '4px' }}>
                点击展开查看完整 JSON
              </summary>
              <pre style={{ 
                padding: '1rem', 
                backgroundColor: '#fafafa', 
                border: '1px solid #eee', 
                borderRadius: '4px',
                maxHeight: '500px',
                overflow: 'auto',
                fontSize: '0.85rem',
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace'
              }}>
                {JSON.stringify(pkg, null, 2)}
              </pre>
            </details>
          </div>
        </>
      ) : (
        <div style={{ padding: '2rem', textAlign: 'center', color: '#999', backgroundColor: '#fafafa', borderRadius: '6px' }}>
          该任务尚无分析包数据
        </div>
      )}
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
