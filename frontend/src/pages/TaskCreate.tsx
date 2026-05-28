import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createTask } from '../api/client';
import type { CreateTaskRequest } from '../types';

interface Account {
  role: string;
  username: string;
  password: string;
}

export default function TaskCreate() {
  const navigate = useNavigate();
  const [targetUrl, setTargetUrl] = useState('');
  const [taskName, setTaskName] = useState('');
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [rules, setRules] = useState('');
  const [focusAreas, setFocusAreas] = useState('');
  const [loading, setLoading] = useState(false);

  const addAccount = () => {
    setAccounts([...accounts, { role: '', username: '', password: '' }]);
  };

  const removeAccount = (index: number) => {
    setAccounts(accounts.filter((_, i) => i !== index));
  };

  const updateAccount = (index: number, field: keyof Account, value: string) => {
    const updated = [...accounts];
    updated[index] = { ...updated[index], [field]: value };
    setAccounts(updated);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetUrl.trim()) return;

    setLoading(true);
    try {
      const request: CreateTaskRequest = {
        target_url: targetUrl.trim(),
        task_name: taskName.trim() || '未命名任务',
        config: {
          accounts: accounts.length > 0 ? accounts : undefined,
          rules: rules.trim() || undefined,
          focus_areas: focusAreas.trim() || undefined,
        },
      };
      const task = await createTask(request);
      navigate(`/monitor/${task.id}`);
    } catch (err) {
      console.error('Failed to create task:', err);
      alert('创建任务失败: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const sectionStyle: React.CSSProperties = {
    marginBottom: '1.5rem',
    padding: '1rem',
    backgroundColor: '#f9f9f9',
    borderRadius: '6px',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block',
    marginBottom: '0.25rem',
    fontWeight: 600,
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '0.5rem',
    border: '1px solid #ccc',
    borderRadius: '4px',
    boxSizing: 'border-box',
    marginBottom: '0.75rem',
  };

  const buttonStyle: React.CSSProperties = {
    padding: '0.6rem 1.2rem',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontWeight: 600,
  };

  return (
    <div style={{ maxWidth: '800px', margin: '2rem auto', padding: '0 1rem' }}>
      <h1>创建测试任务</h1>
      <form onSubmit={handleSubmit}>
        <div style={sectionStyle}>
          <label style={labelStyle}>目标 URL *</label>
          <input
            type="url"
            required
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            placeholder="https://example.com"
            style={inputStyle}
          />

          <label style={labelStyle}>任务名称</label>
          <input
            type="text"
            value={taskName}
            onChange={(e) => setTaskName(e.target.value)}
            placeholder="可选"
            style={inputStyle}
          />
        </div>

        <div style={sectionStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label style={labelStyle}>测试账号</label>
            <button type="button" onClick={addAccount} style={{ ...buttonStyle, backgroundColor: '#e0e0e0' }}>
              + 添加账号
            </button>
          </div>
          {accounts.map((acc, idx) => (
            <div
              key={idx}
              style={{
                display: 'flex',
                gap: '0.5rem',
                marginBottom: '0.5rem',
                alignItems: 'center',
              }}
            >
              <input
                type="text"
                placeholder="角色"
                value={acc.role}
                onChange={(e) => updateAccount(idx, 'role', e.target.value)}
                style={{ ...inputStyle, marginBottom: 0, flex: 1 }}
              />
              <input
                type="text"
                placeholder="用户名"
                value={acc.username}
                onChange={(e) => updateAccount(idx, 'username', e.target.value)}
                style={{ ...inputStyle, marginBottom: 0, flex: 1 }}
              />
              <input
                type="password"
                placeholder="密码"
                value={acc.password}
                onChange={(e) => updateAccount(idx, 'password', e.target.value)}
                style={{ ...inputStyle, marginBottom: 0, flex: 1 }}
              />
              <button
                type="button"
                onClick={() => removeAccount(idx)}
                style={{ ...buttonStyle, backgroundColor: '#ff4d4f', color: '#fff' }}
              >
                删除
              </button>
            </div>
          ))}
        </div>

        <div style={sectionStyle}>
          <label style={labelStyle}>测试规则</label>
          <textarea
            value={rules}
            onChange={(e) => setRules(e.target.value)}
            placeholder="可选：描述测试规则或约束..."
            rows={4}
            style={{ ...inputStyle, resize: 'vertical' }}
          />

          <label style={labelStyle}>关注领域</label>
          <textarea
            value={focusAreas}
            onChange={(e) => setFocusAreas(e.target.value)}
            placeholder="可选：描述需要重点测试的功能模块..."
            rows={4}
            style={{ ...inputStyle, resize: 'vertical' }}
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          style={{
            ...buttonStyle,
            backgroundColor: '#1890ff',
            color: '#fff',
            width: '100%',
            fontSize: '1rem',
          }}
        >
          {loading ? '创建中...' : '开始测试'}
        </button>
      </form>
    </div>
  );
}
