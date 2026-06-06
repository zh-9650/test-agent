import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useWebSocket } from '../hooks/useWebSocket';
import { getTask } from '../api/client';
import type { Task, WSMessage } from '../types';

const typeLabels: Record<string, string> = {
  page_update: '页面更新',
  ai_thinking: 'AI思考',
  action_result: '执行结果',
  assertion_result: '断言结果',
  setup_progress: '初始化进度',
  test_case_complete: '用例完成',
  session_complete: '会话完成',
};

const typeColors: Record<string, string> = {
  page_update: '#1890ff',
  ai_thinking: '#722ed1',
  action_result: '#52c41a',
  assertion_result: '#fa8c16',
  setup_progress: '#13c2c2',
  test_case_complete: '#eb2f96',
  session_complete: '#ff4d4f',
};

function formatMessageData(msg: WSMessage): string {
  if (!msg.data || typeof msg.data !== 'object') {
    return String(msg.data ?? '');
  }

  const data = msg.data;

  switch (msg.type) {
    case 'action_result': {
      const argsStr = data.tool_args && Object.keys(data.tool_args).length > 0 ? JSON.stringify(data.tool_args) : '';
      return `操作: ${data.tool_name || '未知'}${argsStr ? ` (${argsStr})` : ''} | 结果: ${data.result || '无'}`;
    }
    case 'assertion_result':
      return `断言: ${data.status === 'pass' ? '✅ 通过' : '❌ 失败'} | ${data.reasoning || ''}`;
    case 'ai_thinking': {
      let thought: unknown = data.thought || data.thinking || data.text;
      if (Array.isArray(thought)) {
        thought = thought.map((item) => {
          if (item && typeof item === 'object') {
            const record = item as Record<string, unknown>;
            return String(record.thinking || record.text || JSON.stringify(item));
          }
          return String(item);
        }).join('\n');
      } else if (typeof thought === 'object' && thought !== null) {
        const record = thought as Record<string, unknown>;
        thought = record.thinking || record.text || JSON.stringify(thought);
      }
      return typeof thought === 'string' ? thought : JSON.stringify(data);
    }
    case 'page_update':
      return `页面更新: ${data.url || '未知 URL'}`;
    case 'test_case_complete':
      return `用例 ${data.test_case_id || ''}: ${data.status || '完成'}`;
    case 'session_complete':
      return `会话完成: ${data.phase || ''}`;
    default:
      return JSON.stringify(data, null, 2);
  }
}

export default function Monitor() {
  const { taskId } = useParams<{ taskId: string }>();
  const numericTaskId = taskId ? parseInt(taskId, 10) : undefined;
  const { messages, connected, sendStop } = useWebSocket(numericTaskId);
  const [task, setTask] = useState<Task | null>(null);
  const [isStopping, setIsStopping] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!numericTaskId) return;
    getTask(numericTaskId)
      .then(setTask)
      .catch((err) => console.error('Failed to fetch task:', err));
  }, [numericTaskId]);

  const screenshotMessage = [...messages].reverse().find(
    (message) => message.type === 'page_update'
      && typeof message.data?.screenshot === 'string',
  );
  const screenshot = typeof screenshotMessage?.data.screenshot === 'string'
    ? screenshotMessage.data.screenshot
    : null;
  const isComplete = messages.some(
    (message) => message.type === 'session_complete'
      && message.data?.phase !== 'planning_complete',
  );

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [messages.length]);

  const progress =
    task && task.total_tests > 0
      ? Math.round(((task.passed_tests + task.failed_tests) / task.total_tests) * 100)
      : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Header */}
      <div
        style={{
          padding: '0.75rem 1rem',
          borderBottom: '1px solid #ddd',
          backgroundColor: '#fff',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div>
          <h2 style={{ margin: 0 }}>{task?.task_name || '任务监控'}</h2>
          <div style={{ fontSize: '0.85rem', color: '#666' }}>
            状态: {task?.status || '加载中'} | 连接: {connected ? '在线' : '离线'}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{ width: '200px' }}>
            <div
              style={{
                height: '8px',
                backgroundColor: '#f0f0f0',
                borderRadius: '4px',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${progress}%`,
                  height: '100%',
                  backgroundColor: '#52c41a',
                  transition: 'width 0.3s',
                }}
              />
            </div>
            <div style={{ fontSize: '0.75rem', textAlign: 'center', marginTop: '2px' }}>
              {task?.passed_tests || 0}/{task?.total_tests || 0} 完成
            </div>
          </div>
          {task?.status === 'running' && !isComplete && (
            <button
              onClick={() => {
                setIsStopping(true);
                sendStop();
              }}
              disabled={isStopping}
              style={{
                padding: '0.5rem 1rem',
                backgroundColor: isStopping ? '#ccc' : '#ff4d4f',
                color: '#fff',
                border: 'none',
                borderRadius: '4px',
                cursor: isStopping ? 'not-allowed' : 'pointer',
                fontWeight: 600,
              }}
            >
              {isStopping ? '停止中...' : '停止任务'}
            </button>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left Panel: AI Thinking + Action Log */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            borderRight: '1px solid #ddd',
            backgroundColor: '#f5f5f5',
          }}
        >
          <div
            style={{
              padding: '0.5rem 1rem',
              borderBottom: '1px solid #ddd',
              fontWeight: 600,
              backgroundColor: '#fff',
            }}
          >
            执行日志
          </div>
          <div ref={logRef} style={{ flex: 1, overflowY: 'auto', padding: '0.5rem' }}>
            {messages.length === 0 && (
              <div style={{ color: '#999', textAlign: 'center', marginTop: '2rem' }}>
                等待消息...
              </div>
            )}
            {messages.map((msg: WSMessage, idx: number) => (
              <div
                key={idx}
                style={{
                  marginBottom: '0.75rem',
                  padding: '0.5rem',
                  borderRadius: '4px',
                  backgroundColor: '#fff',
                  borderLeft: `3px solid ${typeColors[msg.type] || '#ccc'}`,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                  <span
                    style={{
                      fontWeight: 600,
                      fontSize: '0.8rem',
                      color: typeColors[msg.type] || '#333',
                    }}
                  >
                    {typeLabels[msg.type] || msg.type}
                  </span>
                  <span style={{ fontSize: '0.75rem', color: '#999' }}>
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <div style={{ fontSize: '0.85rem', color: '#333' }}>
                  {(() => {
                    try {
                      const result = formatMessageData(msg);
                      return typeof result === 'string' ? result : JSON.stringify(result);
                    } catch {
                      return JSON.stringify(msg.data);
                    }
                  })()}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Panel: Browser Screenshot */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            backgroundColor: '#e8e8e8',
          }}
        >
          <div
            style={{
              padding: '0.5rem 1rem',
              borderBottom: '1px solid #ddd',
              fontWeight: 600,
              backgroundColor: '#fff',
            }}
          >
            页面截图
          </div>
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '1rem',
            }}
          >
            {screenshot ? (
              <img
                src={`data:image/png;base64,${screenshot}`}
                alt="Current page"
                style={{
                  maxWidth: '100%',
                  maxHeight: '100%',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
                }}
              />
            ) : (
              <div style={{ color: '#999', textAlign: 'center' }}>暂无截图</div>
            )}
          </div>
        </div>
      </div>

      {/* Completion Overlay */}
      {isComplete && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              backgroundColor: '#fff',
              padding: '2rem',
              borderRadius: '8px',
              textAlign: 'center',
            }}
          >
            <h2 style={{ marginTop: 0 }}>测试完成</h2>
            <p>所有测试用例已执行完毕。</p>
            {task && (
              <Link
                to={`/report/${task.id}`}
                style={{
                  display: 'inline-block',
                  marginTop: '1rem',
                  padding: '0.6rem 1.2rem',
                  backgroundColor: '#1890ff',
                  color: '#fff',
                  textDecoration: 'none',
                  borderRadius: '4px',
                  fontWeight: 600,
                }}
              >
                查看报告
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
