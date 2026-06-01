import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createTask, testLayer1 } from '../api/client';
import type { CreateTaskRequest } from '../types';
import DocumentUploader from '../components/DocumentUploader';

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
  const [prd, setPrd] = useState('');
  const [swagger, setSwagger] = useState('');
  const [techDoc, setTechDoc] = useState('');
  const [prototypeUrl, setPrototypeUrl] = useState('');
  const [changelog, setChangelog] = useState('');
  const [loading, setLoading] = useState(false);
  
  const [testingLayer1, setTestingLayer1] = useState(false);
  const [layer1Progress, setLayer1Progress] = useState('');
  const [layer1Result, setLayer1Result] = useState<any>(null);

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
          prd: prd.trim() || undefined,
          swagger: swagger.trim() || undefined,
          tech_doc: techDoc.trim() || undefined,
          prototype_url: prototypeUrl.trim() || undefined,
          changelog: changelog.trim() || undefined,
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

        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0, marginBottom: '1rem', borderBottom: '1px solid #eee', paddingBottom: '0.5rem' }}>知识库注入 (非必填)</h3>
          
          <DocumentUploader
            label="PRD / 需求文档"
            value={prd}
            onChange={setPrd}
            placeholder="粘贴产品需求文档内容，用于指导 AI 探索业务流程..."
          />

          <DocumentUploader
            label="接口文档 (Swagger / API Docs)"
            value={swagger}
            onChange={setSwagger}
            placeholder="粘贴 Swagger JSON 文本或核心接口说明，用于指导 AI 生成深度的边界测试用例..."
            allowUrlFetch={true}
          />

          <label style={labelStyle}>UI 交互原型 (Prototype URL)</label>
          <input
            type="url"
            value={prototypeUrl}
            onChange={(e) => setPrototypeUrl(e.target.value)}
            placeholder="Figma / 蓝湖 等原型链接..."
            style={inputStyle}
          />

          <DocumentUploader
            label="技术实现逻辑 / 架构文档"
            value={techDoc}
            onChange={setTechDoc}
            placeholder="简述底层实现逻辑、异步机制等，帮助 AI 理解潜在的代码痛点..."
          />

          <DocumentUploader
            label="版本变更日志 (Changelog)"
            value={changelog}
            onChange={setChangelog}
            placeholder="本次发版的更新内容，指导 AI 进行重点回归测试..."
          />

          <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid #eee' }}>
            <button
              type="button"
              onClick={async () => {
                setTestingLayer1(true);
                setLayer1Progress('初始化中...');
                setLayer1Result(null);
                try {
                  const res = await testLayer1(prd, swagger, changelog, (msg) => {
                    setLayer1Progress(msg);
                  });
                  setLayer1Result(res);
                } catch (err: any) {
                  alert('测试失败: ' + err.message);
                } finally {
                  setTestingLayer1(false);
                  setLayer1Progress('');
                }
              }}
              disabled={testingLayer1 || (!prd && !swagger && !changelog)}
              style={{
                ...buttonStyle,
                backgroundColor: testingLayer1 ? '#999' : '#52c41a',
                color: '#fff',
                width: '100%'
              }}
            >
              {testingLayer1 ? `🧠 ${layer1Progress}` : '🧪 试运行 Layer 1 (提取知识库 & 状态机)'}
            </button>
            
            {layer1Result && (
              <div style={{ marginTop: '1rem', padding: '1rem', backgroundColor: '#282c34', color: '#abb2bf', borderRadius: '4px', overflowX: 'auto', maxHeight: '500px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
                  <h4 style={{ margin: 0, color: '#61afef' }}>提取结果 (JSON)</h4>
                  <button type="button" onClick={() => setLayer1Result(null)} style={{ background: 'none', border: 'none', color: '#e06c75', cursor: 'pointer' }}>关闭</button>
                </div>
                <pre style={{ margin: 0, fontSize: '0.9rem' }}>
                  {JSON.stringify(layer1Result, null, 2)}
                </pre>
              </div>
            )}
          </div>
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
