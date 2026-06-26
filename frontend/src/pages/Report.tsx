import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  getRunResults,
  getTask,
  getTaskSteps,
  listTaskRuns,
  resumeTask,
} from '../api/client';
import type { CaseResult, ExecutionRun, Task, TaskStep } from '../types';

export default function Report() {
  const { taskId } = useParams<{ taskId: string }>();
  const id = Number(taskId);
  const [task, setTask] = useState<Task | null>(null);
  const [runs, setRuns] = useState<ExecutionRun[]>([]);
  const [runId, setRunId] = useState('');
  const [results, setResults] = useState<CaseResult[]>([]);
  const [steps, setSteps] = useState<TaskStep[]>([]);

  useEffect(() => {
    if (!id) return;
    Promise.all([getTask(id), listTaskRuns(id)]).then(([taskValue, runValue]) => {
      setTask(taskValue);
      setRuns(runValue.runs);
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

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div>
          <h1>{task?.task_name ?? '运行结果'}</h1>
          <p>任务：{task?.status} | 报告：{task?.report_status}</p>
        </div>
        <div>
          <Link to={`/analysis/${id}`}>分析包</Link>{'　'}
          <Link to="/history">历史任务</Link>
        </div>
      </header>

      <label>
        ExecutionRun：
        <select value={runId} onChange={(event) => setRunId(event.target.value)}>
          {runs.map((run) => (
            <option key={run.run_id} value={run.run_id}>
              {run.run_id} ({run.status}) {run.resumed_from_run_id ? '恢复运行' : '首次运行'}
            </option>
          ))}
        </select>
      </label>

      {selectedRun && (
        <p>
          计划 {selectedRun.summary.planned}，通过 {selectedRun.summary.passed}，失败 {selectedRun.summary.failed}，
          未完成 {selectedRun.summary.incomplete}，跳过 {selectedRun.summary.skipped}，
          需人工 {selectedRun.summary.human_review_required}
        </p>
      )}

      {results.map((result) => (
        <section key={result.candidate_case_id} style={{ background: '#fff', padding: 18, margin: '16px 0', borderRadius: 8 }}>
          <h2>{result.candidate_case_id} | {result.terminal_status}</h2>
          <p>{result.summary}</p>
          {result.failure_reason && <p style={{ color: '#b42318' }}>{result.failure_reason}</p>}
          {Array.from({ length: result.attempt_count }, (_, index) => index + 1).map((attempt) => (
            <details key={attempt} open={attempt === result.attempt_count}>
              <summary>Attempt {attempt}</summary>
              {(grouped.get(`${result.candidate_case_id}:${attempt}`) ?? []).map((step) => (
                <div key={step.id} style={{ margin: 8, padding: 8, background: '#f6f8fa' }}>
                  #{step.step_index} {step.action_type} {step.action_target}: {step.result}
                </div>
              ))}
            </details>
          ))}
        </section>
      ))}

      {results.some((result) => result.terminal_status !== 'passed') && task?.status !== 'running' && (
        <button onClick={async () => {
          await resumeTask(id);
          window.location.href = `/monitor/${id}`;
        }}>
          创建新运行并重试非通过用例
        </button>
      )}
    </main>
  );
}
