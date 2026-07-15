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
    return <div className="glass-panel" style={{ maxWidth: '600px', margin: '4rem auto', textAlign: 'center' }}>加载中...</div>;
  }

  if (error) {
    return <div className="glass-panel" style={{ maxWidth: '600px', margin: '4rem auto', textAlign: 'center', color: 'var(--color-failed)' }}>{error}</div>;
  }

  if (!task) {
    return <div className="glass-panel" style={{ maxWidth: '600px', margin: '4rem auto', textAlign: 'center' }}>任务不存在</div>;
  }

  const pkg = task.analysis_package;
  const selection = pkg?.runtime_hints?.execution_selection;
  const isPreExecution = pkg?.runtime_hints?.execution_mode === 'pre_execution';
  const canViewReport = task.report_status === 'completed';
  const findings = pkg?.quality_gate_report?.findings || [];
  const errors = findings.filter((item) => item.severity === 'error');
  const warnings = findings.filter((item) => item.severity === 'warning');

  const branchCounts = (pkg?.candidate_cases || []).reduce<Record<string, number>>((counts, item) => {
    counts[item.branch_type] = (counts[item.branch_type] || 0) + 1;
    return counts;
  }, {});

  const getLifecycleBadgeClass = (status: string) => {
    switch (status) {
      case 'running': return 'badge-running';
      case 'completed': return 'badge-passed';
      case 'failed': return 'badge-failed';
      case 'paused_for_review': return 'badge-review';
      case 'cancelled': return 'badge-skipped';
      default: return 'badge-skipped';
    }
  };

  const getLifecycleLabel = (status: string) => {
    switch (status) {
      case 'pending': return '等待中';
      case 'running': return '执行中';
      case 'completed': return '已完成';
      case 'failed': return '已失败';
      case 'paused_for_review': return '待审核';
      case 'cancelled': return '已取消';
      default: return status;
    }
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '0 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* Title & Action Header */}
      <div className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '1.8rem' }}>测试规划与分析包</h1>
          <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)' }}>查看智能体基于需求与探索生成的测试意图、覆盖设计和执行集路由。</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {canViewReport ? (
            <Link to={`/report/${task.id}`} className="btn btn-primary" style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}>
              查看运行报告
            </Link>
          ) : (
            <Link to={`/monitor/${task.id}`} className="btn btn-primary" style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}>
              返回监控
            </Link>
          )}
          <Link to="/history" className="btn btn-secondary" style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}>
            返回历史
          </Link>
        </div>
      </div>

      {/* Task Metadata Card */}
      <div className="glass-panel">
        <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem', marginBottom: '1rem' }}>基本任务信息</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', fontSize: '0.925rem' }}>
          <div><span style={{ color: 'var(--text-secondary)' }}>任务名称:</span> <strong style={{ color: 'var(--text-primary)' }}>{task.task_name}</strong></div>
          <div>
            <span style={{ color: 'var(--text-secondary)' }}>状态:</span>{' '}
            <span className={`badge ${getLifecycleBadgeClass(task.status)}`}>
              {getLifecycleLabel(task.status)}
            </span>
          </div>
          <div><span style={{ color: 'var(--text-secondary)' }}>目标地址:</span> <code style={{ color: 'var(--accent-blue)' }}>{task.target_url}</code></div>
          <div><span style={{ color: 'var(--text-secondary)' }}>规划时间:</span> <span style={{ color: 'var(--text-primary)' }}>{new Date(task.created_at).toLocaleString()}</span></div>
          <div>
            <span style={{ color: 'var(--text-secondary)' }}>运行模式:</span>{' '}
            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
              {isPreExecution ? '前置设计' : '在线测试'}
            </span>
          </div>
        </div>
      </div>

      {pkg ? (
        <>
          {/* Stat Summary Grid */}
          <section>
            <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
              📊 资产包指标摘要 (Asset Package Metrics)
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
              <StatCard label="需求原子事实 (Requirement Facts)" value={pkg.facts?.length || 0} color="var(--accent-blue)" />
              <StatCard label="推导验证断言 (Assertions)" value={pkg.assertions?.length || 0} color="var(--color-passed)" />
              <StatCard label="人工复核断言 (Manual Review)" value={pkg.manual_review_items?.length || 0} color="var(--color-review)" />
              <StatCard label="页面探索目标 (Exploration Goals)" value={pkg.exploration_goals?.length || 0} color="var(--color-running)" />
              <StatCard label="全量候选资产 (Candidates)" value={pkg.candidate_cases?.length || 0} color="var(--color-incomplete)" />
              <StatCard label="本轮选中执行 (Selected)" value={selection?.selected_count || 0} color="#13c2c2" />
              <StatCard label="本轮挂起资产 (Deferred)" value={selection?.deferred_count || 0} color="var(--color-skipped)" />
            </div>
          </section>

          {/* Quality Gates */}
          {findings.length > 0 && (
            <section className="glass-panel">
              <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
                🛡️ 资产质量门阈断言 (Quality Gates)
              </h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {errors.length > 0 && (
                  <div style={{ borderLeft: '4px solid var(--color-failed)', background: 'var(--bg-failed)', borderRadius: '6px', padding: '1rem' }}>
                    <h4 style={{ color: 'var(--color-failed)', margin: '0 0 0.5rem 0' }}>❌ 阻断性异常 / 错误 ({errors.length})</h4>
                    <ul style={{ margin: 0, paddingLeft: '1.25rem', color: 'var(--text-primary)', fontSize: '0.9rem', lineHeight: '1.5' }}>
                      {errors.map((item, index) => <li key={`${item.code}-${index}`}>{item.message}</li>)}
                    </ul>
                  </div>
                )}
                {warnings.length > 0 && (
                  <div style={{ borderLeft: '4px solid var(--color-incomplete)', background: 'var(--bg-incomplete)', borderRadius: '6px', padding: '1rem' }}>
                    <h4 style={{ color: 'var(--color-incomplete)', margin: '0 0 0.5rem 0' }}>⚠️ 规范性警告 ({warnings.length})</h4>
                    <ul style={{ margin: 0, paddingLeft: '1.25rem', color: 'var(--text-primary)', fontSize: '0.9rem', lineHeight: '1.5' }}>
                      {warnings.map((item, index) => <li key={`${item.code}-${index}`}>{item.message}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* Execution Selection Rules - Cleaned Up */}
          {selection && (
            <section className="glass-panel">
              <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1rem' }}>
                ⚙️ 用例选择路由规则 (Execution Selection)
              </h2>
              <p style={{ margin: '0 0 1rem 0', fontSize: '0.95rem' }}>
                本轮采用策略 <strong style={{ color: 'var(--accent-blue)' }}>{selection.profile}</strong>，
                目标用例数 {selection.target_count ?? '无限制'}。其中必须执行的用例骨架 {selection.mandatory_count} 个，实际选中 {selection.selected_count} 个，挂起 {selection.deferred_count} 个。
              </p>

              <h4 style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>选中与延后决策依据 (Selection Details)</h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem' }}>
                {Object.entries(selection.selection_reasons || {}).map(([caseId, reason]) => (
                  <div key={caseId} className="glass-card" style={{ padding: '0.75rem 1rem', fontSize: '0.85rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                      <strong style={{ fontFamily: 'var(--font-mono)' }}>{caseId}</strong>
                      <span className={`badge ${String(reason).includes('defer') || String(reason).includes('延后') ? 'badge-skipped' : 'badge-passed'}`} style={{ fontSize: '0.65rem' }}>
                        {String(reason).includes('defer') || String(reason).includes('延后') ? '挂起' : '选中'}
                      </span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)', lineHeight: '1.4' }}>{String(reason)}</div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Coverage blueprint */}
          <section className="glass-panel">
            <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
              🎯 测试覆盖蓝图 (Coverage Blueprint)
            </h2>
            <p style={{ margin: '0 0 1rem 0', fontSize: '0.95rem' }}>
              分析提炼的测试拓扑：包含核心业务模块 {pkg.coverage_blueprint?.modules?.length || 0} 个，核心链路流程 {pkg.coverage_blueprint?.business_flows?.length || 0} 条，模块依赖关系 {pkg.coverage_blueprint?.dependencies?.length || 0} 组。
            </p>

            <h4 style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.9rem' }}>业务覆盖类型分布</h4>
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
              {Object.entries(branchCounts).map(([branch, count]) => (
                <div key={branch} className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0.8rem', borderRadius: '6px' }}>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{branch}</span>
                  <span className="badge badge-running" style={{ padding: '0.1rem 0.4rem', fontSize: '0.75rem' }}>{count}</span>
                </div>
              ))}
            </div>

            {/* System Map Details - Cleaned Up */}
            {pkg.system_map && (
              <div>
                <h4 style={{ color: 'var(--text-primary)', marginBottom: '0.75rem', fontSize: '0.95rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.25rem' }}>
                  🗺️ 网页系统拓扑地图 (System Map)
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.25rem' }}>

                  {/* Pages */}
                  <div className="glass-card" style={{ background: 'rgba(255,255,255,0.005)' }}>
                    <strong style={{ display: 'block', marginBottom: '0.75rem', color: 'var(--accent-blue)', borderBottom: '1px solid rgba(255,255,255,0.04)', paddingBottom: '0.25rem' }}>
                      识别页面 ({pkg.system_map.pages?.length || 0})
                    </strong>
                    <ul style={{ maxHeight: '180px', overflowY: 'auto', margin: 0, paddingLeft: '1.25rem', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: '1.6' }}>
                      {pkg.system_map.pages?.map((page, i) => (
                        <li key={i}>{page.title || page.url_pattern || `页面 ${i + 1}`}</li>
                      ))}
                    </ul>
                  </div>

                  {/* Actions */}
                  <div className="glass-card" style={{ background: 'rgba(255,255,255,0.005)' }}>
                    <strong style={{ display: 'block', marginBottom: '0.75rem', color: 'var(--color-passed)', borderBottom: '1px solid rgba(255,255,255,0.04)', paddingBottom: '0.25rem' }}>
                      页面操作入口 ({pkg.system_map.actions?.length || 0})
                    </strong>
                    <ul style={{ maxHeight: '180px', overflowY: 'auto', margin: 0, paddingLeft: '1.25rem', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: '1.6' }}>
                      {pkg.system_map.actions?.map((action, i) => (
                        <li key={i}>{action.action_name || `操作 ${i + 1}`}</li>
                      ))}
                    </ul>
                  </div>

                  {/* Forms */}
                  <div className="glass-card" style={{ background: 'rgba(255,255,255,0.005)' }}>
                    <strong style={{ display: 'block', marginBottom: '0.75rem', color: 'var(--color-incomplete)', borderBottom: '1px solid rgba(255,255,255,0.04)', paddingBottom: '0.25rem' }}>
                      核心交互表单 ({pkg.system_map.forms?.length || 0})
                    </strong>
                    <ul style={{ maxHeight: '180px', overflowY: 'auto', margin: 0, paddingLeft: '1.25rem', fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: '1.6' }}>
                      {pkg.system_map.forms?.map((form, i) => (
                        <li key={i}>{form.form_name || `表单 ${i + 1}`}</li>
                      ))}
                    </ul>
                  </div>

                </div>
              </div>
            )}
          </section>

          {/* Raw JSON */}
          <section className="glass-panel">
            <h2 style={{ fontSize: '1.2rem', margin: 0 }}>🗄️ 原始测试资产包数据 (JSON)</h2>
            <details style={{ marginTop: '0.75rem' }}>
              <summary style={{ cursor: 'pointer', padding: '0.5rem 1rem', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', borderRadius: '6px', color: 'var(--text-secondary)', fontSize: '0.85rem', outline: 'none' }}>
                点击展开完整资产包结构 JSON
              </summary>
              <pre style={{
                padding: '1rem',
                backgroundColor: '#040508',
                border: '1px solid rgba(255,255,255,0.04)',
                borderRadius: '6px',
                maxHeight: '400px',
                overflow: 'auto',
                fontSize: '0.8rem',
                color: '#a7f3d0',
                fontFamily: 'var(--font-mono)',
                marginTop: '0.5rem'
              }}>
                {JSON.stringify(pkg, null, 2)}
              </pre>
            </details>
          </section>
        </>
      ) : (
        <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          🛸 该任务尚无分析包数据，生命周期仍在执行中或遇到异常中止。
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div
      style={{
        padding: '1.25rem 1rem',
        borderRadius: '8px',
        backgroundColor: 'rgba(255, 255, 255, 0.015)',
        border: `1px solid ${color}22`,
        textAlign: 'center',
        boxShadow: 'var(--shadow-sm)'
      }}
    >
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontWeight: 500 }}>{label}</div>
      <div style={{ fontSize: '1.75rem', fontWeight: 700, color: color }}>{value}</div>
    </div>
  );
}
