import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  decideHumanReview,
  getTask,
  listHumanReviews,
  resumeTask,
  stopTask,
} from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import type { HumanReviewRequest, Task } from '../types';

export default function Monitor() {
  const { taskId } = useParams<{ taskId: string }>();
  const id = Number(taskId);
  const { messages, connected } = useWebSocket(id);
  const [task, setTask] = useState<Task | null>(null);
  const [reviews, setReviews] = useState<HumanReviewRequest[]>([]);
  const [stopping, setStopping] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [decidingId, setDecidingId] = useState<number | null>(null);

  useEffect(() => {
    if (!id) return;
    let active = true;
    const refresh = () => Promise
      .all([getTask(id), listHumanReviews(id)])
      .then(([taskValue, reviewValue]) => {
        if (!active) return;
        setTask(taskValue);
        setReviews(reviewValue.requests);
      });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [id]);

  const summary = task?.latest_run?.summary;
  const progress = summary?.planned
    ? Math.round((summary.terminal / summary.planned) * 100)
    : 0;
  const canViewReport = task?.report_status === 'completed';
  const canViewAnalysis = Boolean(task?.analysis_package);
  const pendingReviews = reviews.filter((review) => review.status === 'pending');

  // Clean logs helper
  const formattedLogs = useMemo(() => {
    return messages.map((msg) => {
      const time = new Date(msg.timestamp).toLocaleTimeString();
      let text: string;
      let typeClass = 'terminal-line';

      switch (msg.type) {
        case 'phase_started':
          text = `🟢 阶段开始 [${msg.data?.phase ?? ''}]`;
          break;
        case 'phase_completed':
          text = `✅ 阶段完成 [${msg.data?.phase ?? ''}]`;
          break;
        case 'case_started':
          text = `📋 用例拉起: ${msg.candidate_case_id ?? ''}`;
          break;
        case 'case_attempt_started':
          text = `🔄 用例 ${msg.candidate_case_id ?? ''} 尝试 #${msg.data?.attempt_no ?? 1} 开始...`;
          break;
        case 'case_completed':
          text = `ℹ️ 用例 ${msg.candidate_case_id ?? ''} 尝试完成`;
          break;
        case 'session_completed':
          text = `🎉 任务全部完成！`;
          break;
        case 'session_failed':
          text = `🚨 任务执行失败: ${msg.data?.failure_reason ?? ''}`;
          typeClass = 'terminal-line text-danger';
          break;
        case 'session_cancelled':
          text = `⏹️ 任务已被用户取消`;
          break;
        case 'session_paused_for_review':
          text = `⏳ 任务已暂停，等待人工审查...`;
          break;
        default:
          text = `${msg.type} - ${JSON.stringify(msg.data)}`;
      }

      return { time, type: msg.type, text, typeClass };
    });
  }, [messages]);

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
      case 'running': return '进行中';
      case 'completed': return '已完成';
      case 'failed': return '执行失败';
      case 'paused_for_review': return '待审核';
      case 'cancelled': return '已取消';
      default: return status;
    }
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '0 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* Header Panel */}
      <header className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ margin: '0 0 0.5rem 0', fontSize: '1.8rem' }}>
            {task?.task_name ?? '任务监控'}
          </h1>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center', fontSize: '0.9rem' }}>
            <div>
              生命周期：
              <span className={`badge ${task ? getLifecycleBadgeClass(task.status) : ''}`}>
                {task ? getLifecycleLabel(task.status) : '加载中'}
              </span>
            </div>
            <div style={{ color: 'var(--text-secondary)' }}>
              当前阶段：<span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{task?.phase ?? '无'}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <span style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: connected ? 'var(--color-passed)' : 'var(--color-failed)',
                display: 'inline-block'
              }} />
              <span style={{ color: 'var(--text-muted)' }}>
                {connected ? '实时连接中' : '连接已断开 (使用轮询机制)'}
              </span>
            </div>
          </div>
          {task?.failure_reason && (
            <div style={{ color: 'var(--color-failed)', fontSize: '0.9rem', marginTop: '0.75rem', padding: '0.5rem 1rem', background: 'var(--bg-failed)', borderRadius: '6px', border: '1px solid rgba(244, 63, 94, 0.2)' }}>
              失败原因：{task.failure_reason}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          {task?.status === 'running' && (
            <button
              disabled={stopping}
              onClick={async () => {
                setStopping(true);
                try {
                  await stopTask(id);
                  setTask(await getTask(id));
                } finally {
                  setStopping(false);
                }
              }}
              className="btn btn-danger"
            >
              {stopping ? '正在停止...' : '停止任务'}
            </button>
          )}

          {task?.status !== 'running' && canViewReport && (
            <Link to={`/report/${id}`} className="btn btn-primary">
              查看测试报告
            </Link>
          )}

          {task?.status !== 'running' && !canViewReport && canViewAnalysis && (
            <Link to={`/analysis/${id}`} className="btn btn-primary">
              查看分析包
            </Link>
          )}

          {task?.status === 'paused_for_review' && pendingReviews.length === 0 && (
            <button
              disabled={resuming}
              onClick={async () => {
                setResuming(true);
                try {
                  await resumeTask(id);
                  setTask(await getTask(id));
                } finally {
                  setResuming(false);
                }
              }}
              className="btn btn-success"
            >
              {resuming ? '正在恢复...' : '恢复执行'}
            </button>
          )}

          {task?.status !== 'running' && task?.report_status === 'failed' && (
            <span className="badge badge-failed">报告生成失败</span>
          )}
        </div>
      </header>

      {/* Progress & Stat Cards */}
      <section className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: '1.1rem' }}>用例执行进度</h3>
          <span style={{ fontWeight: 700, color: 'var(--accent-blue)', fontSize: '1.1rem' }}>
            {summary?.terminal ?? 0} / {summary?.planned ?? 0} ({progress}%)
          </span>
        </div>

        {/* Animated Gradient Progress Bar */}
        <div style={{ height: '8px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px', overflow: 'hidden' }}>
          <div style={{
            width: `${progress}%`,
            height: '100%',
            background: 'var(--primary-gradient)',
            boxShadow: '0 0 10px rgba(99, 102, 241, 0.5)',
            borderRadius: '4px',
            transition: 'width 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
          }} />
        </div>

        {/* Stats Count Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '1rem', marginTop: '0.5rem' }}>
          <StatMiniCard label="通过" value={summary?.passed ?? 0} color="var(--color-passed)" bg="var(--bg-passed)" />
          <StatMiniCard label="失败" value={summary?.failed ?? 0} color="var(--color-failed)" bg="var(--bg-failed)" />
          <StatMiniCard label="需人工审核" value={summary?.human_review_required ?? 0} color="var(--color-review)" bg="var(--bg-review)" />
          <StatMiniCard label="未完成" value={summary?.incomplete ?? 0} color="var(--color-incomplete)" bg="var(--bg-incomplete)" />
          <StatMiniCard label="跳过" value={summary?.skipped ?? 0} color="var(--color-skipped)" bg="var(--bg-skipped)" />
        </div>
      </section>

      {/* Human Reviews (HITL Queue) */}
      <section className="glass-panel">
        <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
          ⏳ 待处理人工审查 ({pendingReviews.length})
        </h2>
        {reviews.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', margin: '1rem 0' }}>暂无人工审查请求。</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {reviews.map((review) => (
              <div
                key={review.id}
                className="glass-card"
                style={{
                  borderLeft: `3px solid ${review.status === 'pending' ? 'var(--color-review)' : 'var(--border-color)'}`,
                  background: 'rgba(255, 255, 255, 0.015)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>审查请求 #{review.id}</span>
                    <span className="badge badge-skipped" style={{ fontSize: '0.7rem' }}>{review.phase}</span>
                    {review.candidate_case_id && (
                      <span className="badge badge-review" style={{ fontSize: '0.7rem' }}>{review.candidate_case_id}</span>
                    )}
                  </div>
                  <span className={`badge ${review.status === 'pending' ? 'badge-review' : 'badge-skipped'}`} style={{ fontSize: '0.7rem' }}>
                    {review.status === 'pending' ? '待审核' : review.status === 'approved' ? '已批准' : '已拒绝'}
                  </span>
                </div>
                <p style={{ margin: '0.5rem 0', color: 'var(--text-primary)', fontSize: '0.925rem', whiteSpace: 'pre-wrap', lineHeight: '1.5' }}>
                  {review.reason}
                </p>
                {review.evidence_refs.length > 0 && (
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
                    🔍 关联证据：<code>{review.evidence_refs.join(', ')}</code>
                  </div>
                )}
                {review.status === 'pending' && (
                  <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
                    <button
                      disabled={decidingId === review.id}
                      onClick={async () => {
                        setDecidingId(review.id);
                        try {
                          await decideHumanReview(review.id, 'approved', '前端批准继续');
                          setReviews((current) => current.map((item) => (
                            item.id === review.id ? { ...item, status: 'approved' } : item
                          )));
                        } finally {
                          setDecidingId(null);
                        }
                      }}
                      className="btn btn-success"
                      style={{ padding: '0.4rem 1rem', fontSize: '0.85rem' }}
                    >
                      批准通过
                    </button>
                    <button
                      disabled={decidingId === review.id}
                      onClick={async () => {
                        setDecidingId(review.id);
                        try {
                          await decideHumanReview(review.id, 'rejected', '前端拒绝继续');
                          setReviews((current) => current.map((item) => (
                            item.id === review.id ? { ...item, status: 'rejected' } : item
                          )));
                        } finally {
                          setDecidingId(null);
                        }
                      }}
                      className="btn btn-danger"
                      style={{ padding: '0.4rem 1rem', fontSize: '0.85rem' }}
                    >
                      拒绝继续
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Terminal Live logs */}
      <section className="glass-panel" style={{ paddingBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.3rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.25rem' }}>
          💻 实时控制台日志
        </h2>

        <div className="terminal-container">
          <div className="terminal-header">
            <div className="terminal-dots">
              <div className="terminal-dot dot-red"></div>
              <div className="terminal-dot dot-yellow"></div>
              <div className="terminal-dot dot-green"></div>
            </div>
            <div className="terminal-title">live_event_stream.sh</div>
            <div style={{ width: '40px' }}></div>
          </div>

          <div className="terminal-body" style={{ minHeight: '200px' }}>
            {formattedLogs.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', margin: 0, fontStyle: 'italic' }}>
                ⌛ 正在建立 WebSocket 连接并同步状态...
              </p>
            ) : (
              formattedLogs.map((log, index) => (
                <div key={index} style={{ marginBottom: '0.35rem', fontFamily: 'var(--font-mono)' }}>
                  <span className="terminal-line-timestamp">[{log.time}]</span>
                  <span className={log.typeClass}>{log.text}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function StatMiniCard({ label, value, color, bg }: { label: string; value: number; color: string; bg: string }) {
  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.015)',
      border: '1px solid var(--border-color)',
      borderRadius: '8px',
      padding: '0.75rem 1rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: '0.5rem'
    }}>
      <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{label}</span>
      <span style={{
        fontWeight: 700,
        fontSize: '1.1rem',
        color: color,
        background: bg,
        padding: '0.15rem 0.5rem',
        borderRadius: '6px',
        minWidth: '32px',
        textAlign: 'center'
      }}>
        {value}
      </span>
    </div>
  );
}
