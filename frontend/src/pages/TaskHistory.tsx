import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listTasks, deleteTask } from '../api/client';
import type { Task } from '../types';

export default function TaskHistory() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const limit = 20;

  const fetchTasks = async (offset: number) => {
    setLoading(true);
    try {
      const res = await listTasks(offset, limit);
      setTasks((prev) => (offset === 0 ? res.tasks : [...prev, ...res.tasks]));
      setTotal(res.total);
    } catch (err) {
      console.error('Failed to fetch tasks:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks(0);
  }, []);

  const handleDelete = async (taskId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm('确定要删除这个任务吗？')) return;
    try {
      await deleteTask(taskId);
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
    } catch (err) {
      console.error('Failed to delete task:', err);
      alert('删除失败');
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return '#52c41a';
      case 'failed':
        return '#ff4d4f';
      case 'running':
        return '#1890ff';
      default:
        return '#fa8c16';
    }
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '2rem 1rem' }}>
      <h1 style={{ marginBottom: '1.5rem' }}>历史任务</h1>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', backgroundColor: '#fff', borderRadius: '6px', overflow: 'hidden' }}>
          <thead>
            <tr style={{ backgroundColor: '#fafafa', borderBottom: '2px solid #f0f0f0' }}>
              <th style={{ padding: '0.75rem', textAlign: 'left', fontWeight: 600 }}>任务名称</th>
              <th style={{ padding: '0.75rem', textAlign: 'left', fontWeight: 600 }}>目标 URL</th>
              <th style={{ padding: '0.75rem', textAlign: 'center', fontWeight: 600 }}>状态</th>
              <th style={{ padding: '0.75rem', textAlign: 'center', fontWeight: 600 }}>通过/失败/总计</th>
              <th style={{ padding: '0.75rem', textAlign: 'left', fontWeight: 600 }}>创建时间</th>
              <th style={{ padding: '0.75rem', textAlign: 'center', fontWeight: 600 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr
                key={task.id}
                onClick={() => navigate(`/report/${task.id}`)}
                style={{ cursor: 'pointer', borderBottom: '1px solid #f0f0f0' }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLTableRowElement).style.backgroundColor = '#fafafa';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLTableRowElement).style.backgroundColor = '#fff';
                }}
              >
                <td style={{ padding: '0.75rem' }}>{task.task_name}</td>
                <td style={{ padding: '0.75rem', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {task.target_url}
                </td>
                <td style={{ padding: '0.75rem', textAlign: 'center' }}>
                  <span
                    style={{
                      padding: '0.25rem 0.5rem',
                      borderRadius: '4px',
                      backgroundColor: statusColor(task.status) + '22',
                      color: statusColor(task.status),
                      fontWeight: 600,
                      fontSize: '0.8rem',
                    }}
                  >
                    {task.status}
                  </span>
                </td>
                <td style={{ padding: '0.75rem', textAlign: 'center' }}>
                  {task.passed_tests}/{task.failed_tests}/{task.total_tests}
                </td>
                <td style={{ padding: '0.75rem', fontSize: '0.85rem', color: '#666' }}>
                  {new Date(task.created_at).toLocaleString()}
                </td>
                <td style={{ padding: '0.75rem', textAlign: 'center' }}>
                  <button
                    onClick={(e) => handleDelete(task.id, e)}
                    style={{
                      padding: '0.25rem 0.5rem',
                      border: 'none',
                      borderRadius: '4px',
                      backgroundColor: '#ff4d4f',
                      color: '#fff',
                      cursor: 'pointer',
                      fontSize: '0.8rem',
                    }}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
            {tasks.length === 0 && !loading && (
              <tr>
                <td colSpan={6} style={{ padding: '2rem', textAlign: 'center', color: '#999' }}>
                  暂无任务记录
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {tasks.length < total && (
        <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
          <button
            onClick={() => {
              const nextSkip = skip + limit;
              setSkip(nextSkip);
              fetchTasks(nextSkip);
            }}
            disabled={loading}
            style={{
              padding: '0.5rem 1.5rem',
              border: '1px solid #d9d9d9',
              borderRadius: '4px',
              backgroundColor: '#fff',
              cursor: loading ? 'not-allowed' : 'pointer',
              color: '#333',
            }}
          >
            {loading ? '加载中...' : '加载更多'}
          </button>
        </div>
      )}
    </div>
  );
}
