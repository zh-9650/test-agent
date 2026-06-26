import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getTask, stopTask } from '../api/client';
import { useWebSocket } from '../hooks/useWebSocket';
import type { Task } from '../types';

export default function Monitor() {
  const { taskId } = useParams<{ taskId: string }>();
  const id = Number(taskId);
  const { messages, connected } = useWebSocket(id);
  const [task, setTask] = useState<Task | null>(null);
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    if (!id) return;
    let active = true;
    const refresh = () => getTask(id).then((value) => active && setTask(value));
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
  const finalMessage = useMemo(
    () => [...messages].reverse().find((message) => message.type.startsWith('session_')),
    [messages],
  );

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1>{task?.task_name ?? '任务监控'}</h1>
          <p>
            生命周期：{task?.status ?? '加载中'} {' | '}
            阶段：{task?.phase ?? '-'} {' | '}
            WebSocket：{connected ? '已连接' : '已断开，使用 REST 恢复'}
          </p>
          {task?.failure_reason && <p style={{ color: '#b42318' }}>{task.failure_reason}</p>}
        </div>
        <div>
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
            >
              {stopping ? '正在停止...' : '停止任务'}
            </button>
          )}
          {task?.status !== 'running' && canViewReport && (
            <Link to={`/report/${id}`}>查看运行结果</Link>
          )}
          {task?.status !== 'running' && task?.report_status === 'failed' && (
            <span style={{ color: '#b42318' }}>报告生成失败</span>
          )}
        </div>
      </header>

      <section style={{ background: '#fff', padding: 16, borderRadius: 8 }}>
        <div style={{ height: 10, background: '#eee', borderRadius: 5 }}>
          <div style={{ width: `${progress}%`, height: '100%', background: '#1677ff', borderRadius: 5 }} />
        </div>
        <p>{summary?.terminal ?? 0}/{summary?.planned ?? 0} 已产生终态结果（{progress}%）</p>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <span>通过 {summary?.passed ?? 0}</span>
          <span>失败 {summary?.failed ?? 0}</span>
          <span>未完成 {summary?.incomplete ?? 0}</span>
          <span>跳过 {summary?.skipped ?? 0}</span>
          <span>需人工 {summary?.human_review_required ?? 0}</span>
        </div>
      </section>

      <section>
        <h2>事件流</h2>
        {messages.map((message, index) => (
          <pre key={`${message.timestamp}-${index}`} style={{ whiteSpace: 'pre-wrap', background: '#f6f8fa', padding: 12 }}>
            {message.type} {message.phase ?? ''} {message.candidate_case_id}
            {'\n'}{JSON.stringify(message.data, null, 2)}
          </pre>
        ))}
        {!messages.length && <p>等待事件。页面会通过 REST 持续恢复权威状态。</p>}
        {finalMessage && <p>最终事件：{finalMessage.type}</p>}
      </section>
    </main>
  );
}
