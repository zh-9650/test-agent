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

  return (
    <main style={{ maxWidth: 1200, margin: '0 auto', padding: 24 }}>
      <h1>历史任务</h1>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr><th>任务</th><th>生命周期</th><th>阶段</th><th>最新运行</th><th>报告</th><th>操作</th></tr></thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id} onClick={() => navigate(`/report/${task.id}`)} style={{ cursor: 'pointer' }}>
              <td>{task.task_name}<br /><small>{task.target_url}</small></td>
              <td>{task.status}</td>
              <td>{task.phase ?? '-'}</td>
              <td>
                {task.latest_run
                  ? `${task.latest_run.summary.passed}/${task.latest_run.summary.planned} passed`
                  : '-'}
              </td>
              <td>{task.report_status}</td>
              <td>
                <button onClick={async (event) => {
                  event.stopPropagation();
                  await deleteTask(task.id);
                  setTasks((current) => current.filter((item) => item.id !== task.id));
                }}>删除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
