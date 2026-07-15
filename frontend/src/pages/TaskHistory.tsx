import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { deleteTask, listTasks } from '../api/client';
import type { Task } from '../types';

export default function TaskHistory() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    void listTasks().then((response) => setTasks(response.tasks));
  }, []);

  const getStatusBadgeClass = (status: string) => {
    switch (status) {
      case 'running': return 'badge-running';
      case 'completed': return 'badge-passed';
      case 'failed': return 'badge-failed';
      case 'paused_for_review': return 'badge-review';
      case 'cancelled': return 'badge-skipped';
      default: return 'badge-skipped';
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'pending': return '等待中';
      case 'running': return '执行中';
      case 'completed': return '已完成';
      case 'failed': return '执行失败';
      case 'paused_for_review': return '待审核';
      case 'cancelled': return '已取消';
      default: return status;
    }
  };

  const getPrimaryPath = (task: Task) => {
    if (task.report_status === 'completed') return `/report/${task.id}`;
    if (task.analysis_package) return `/analysis/${task.id}`;
    return `/monitor/${task.id}`;
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '0 1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <div>
          <h1 style={{ margin: 0 }}>历史测试任务</h1>
          <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)' }}>查看过往测试任务的执行进度、分析包与详细报告。</p>
        </div>
        <button onClick={() => navigate('/')} className="btn btn-primary">
          + 创建新任务
        </button>
      </div>

      <div className="glass-panel" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="table-container" style={{ border: 'none', borderRadius: 0, background: 'transparent' }}>
          <table className="custom-table">
            <thead>
              <tr>
                <th style={{ width: '30%' }}>任务名称 / 目标地址</th>
                <th style={{ width: '15%' }}>生命周期</th>
                <th style={{ width: '15%' }}>当前阶段</th>
                <th style={{ width: '15%' }}>最近运行情况</th>
                <th style={{ width: '10%' }}>报告状态</th>
                <th style={{ width: '15%', textAlign: 'center' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr
                  key={task.id}
                  onClick={() => navigate(getPrimaryPath(task))}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                      {task.task_name || '未命名任务'}
                    </div>
                    <code style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {task.target_url}
                    </code>
                  </td>
                  <td>
                    <span className={`badge ${getStatusBadgeClass(task.status)}`}>
                      {getStatusLabel(task.status)}
                    </span>
                  </td>
                  <td>
                    <span style={{
                      fontSize: '0.9rem',
                      color: task.phase ? 'var(--text-primary)' : 'var(--text-muted)'
                    }}>
                      {task.phase ?? '未开始'}
                    </span>
                  </td>
                  <td>
                    {task.latest_run ? (
                      <div style={{ fontSize: '0.85rem' }}>
                        <span style={{ color: 'var(--color-passed)', fontWeight: 600 }}>
                          {task.latest_run.summary.passed} 通
                        </span>
                        {' / '}
                        <span style={{ color: 'var(--color-failed)', fontWeight: 600 }}>
                          {task.latest_run.summary.failed} 败
                        </span>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '0.15rem' }}>
                          共 {task.latest_run.summary.planned} 用例
                        </div>
                      </div>
                    ) : (
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>-</span>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${task.report_status === 'completed' ? 'badge-passed' : task.report_status === 'failed' ? 'badge-failed' : 'badge-skipped'}`}>
                      {task.report_status === 'completed' ? '已生成' : task.report_status === 'failed' ? '失败' : task.report_status === 'skipped' ? '未生成' : '挂起'}
                    </span>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
                      <button
                        onClick={() => navigate(`/monitor/${task.id}`)}
                        className="btn btn-secondary"
                        style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}
                      >
                        监控
                      </button>
                      {task.analysis_package && (
                        <button
                          onClick={() => navigate(`/analysis/${task.id}`)}
                          className="btn btn-secondary"
                          style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}
                        >
                          分析
                        </button>
                      )}
                      <button
                        onClick={async () => {
                          if (confirm('确定删除此任务及其所有的测试结果和步骤数据吗？')) {
                            await deleteTask(task.id);
                            setTasks((current) => current.filter((item) => item.id !== task.id));
                          }
                        }}
                        className="btn btn-danger"
                        style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {tasks.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                    <div>📂 暂无历史测试任务</div>
                    <button
                      onClick={() => navigate('/')}
                      className="btn btn-primary"
                      style={{ marginTop: '1rem', padding: '0.5rem 1rem', fontSize: '0.85rem' }}
                    >
                      立即创建第一个任务
                    </button>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
