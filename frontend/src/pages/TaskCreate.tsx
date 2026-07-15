import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createTask } from '../api/client';
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
  const [prototypeSource, setPrototypeSource] = useState('');
  const [changelog, setChangelog] = useState('');
  const [loading, setLoading] = useState(false);
  const [executionMode, setExecutionMode] = useState<'online' | 'pre_execution'>('online');
  const [executionProfile, setExecutionProfile] = useState<'smoke' | 'balanced' | 'full'>('balanced');
  const [executionTarget, setExecutionTarget] = useState('60');

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
          prototype_source: prototypeSource.trim() || undefined,
          changelog: changelog.trim() || undefined,
          execution_mode: executionMode,
          execution_profile: executionProfile,
          execution_target: executionProfile === 'full'
            ? undefined
            : Math.max(1, Number.parseInt(executionTarget, 10) || (executionProfile === 'smoke' ? 20 : 60)),
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

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '0 1.5rem' }}>
      <div style={{ marginBottom: '2.5rem', textAlign: 'center' }}>
        <h1 style={{ marginBottom: '0.75rem' }}>创建自动化测试任务</h1>
        <p style={{ fontSize: '1.1rem', maxWidth: '600px', margin: '0 auto' }}>
          输入被测系统的 URL 和相关背景文档，AI 智能体将自动探索网页、设计并执行用例。
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))', gap: '2rem', marginBottom: '2rem' }}>

          {/* Left Column: Core Configurations */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>

            {/* Target URL & Task Name */}
            <div className="glass-panel" style={{ flex: 1 }}>
              <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.5rem' }}>基本配置</h3>

              <div className="form-group">
                <label className="form-label">目标系统 URL *</label>
                <input
                  type="url"
                  required
                  value={targetUrl}
                  onChange={(e) => setTargetUrl(e.target.value)}
                  placeholder="https://example.com"
                  className="form-input"
                />
              </div>

              <div className="form-group">
                <label className="form-label">任务名称</label>
                <input
                  type="text"
                  value={taskName}
                  onChange={(e) => setTaskName(e.target.value)}
                  placeholder="如：登录流回归测试 (可选)"
                  className="form-input"
                />
              </div>
            </div>

            {/* Execution Strategy */}
            <div className="glass-panel">
              <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.5rem' }}>执行策略</h3>

              <div className="form-group">
                <label className="form-label">运行模式</label>
                <select
                  value={executionMode}
                  onChange={(event) => setExecutionMode(event.target.value as 'online' | 'pre_execution')}
                  className="form-select"
                >
                  <option value="online">在线测试：探索、设计并执行</option>
                  <option value="pre_execution">前置设计：仅生成测试资产</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">测试策略</label>
                <select
                  value={executionProfile}
                  onChange={(event) => {
                    const profile = event.target.value as 'smoke' | 'balanced' | 'full';
                    setExecutionProfile(profile);
                    if (profile === 'smoke') setExecutionTarget('20');
                    if (profile === 'balanced') setExecutionTarget('60');
                  }}
                  className="form-select"
                >
                  <option value="smoke">Smoke：核心冒烟，最大 30 条用例</option>
                  <option value="balanced">Balanced：高风险覆盖，推荐</option>
                  <option value="full">Full：完整候选资产池</option>
                </select>
              </div>

              {executionProfile !== 'full' && (
                <div className="form-group">
                  <label className="form-label">目标执行数</label>
                  <input
                    type="number"
                    min={1}
                    max={executionProfile === 'smoke' ? 30 : undefined}
                    value={executionTarget}
                    onChange={(event) => setExecutionTarget(event.target.value)}
                    className="form-input"
                  />
                </div>
              )}

              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', lineHeight: '1.4' }}>
                💡 目标数是软目标。为保证测试覆盖，核心流程和高风险测试义务形成的必选骨架可能突破该目标。
              </div>
            </div>

            {/* Test Accounts */}
            <div className="glass-panel">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.5rem' }}>
                <h3 style={{ margin: 0 }}>测试账号</h3>
                <button type="button" onClick={addAccount} className="btn btn-secondary" style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem' }}>
                  + 添加账号
                </button>
              </div>

              {accounts.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', textAlign: 'center', padding: '1rem 0' }}>
                  暂未添加账号（适用于公开免登录系统）
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {accounts.map((acc, idx) => (
                    <div key={idx} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <input
                        type="text"
                        placeholder="角色 (管理员)"
                        value={acc.role}
                        onChange={(e) => updateAccount(idx, 'role', e.target.value)}
                        className="form-input"
                        style={{ flex: 1, padding: '0.5rem' }}
                      />
                      <input
                        type="text"
                        placeholder="用户名"
                        value={acc.username}
                        onChange={(e) => updateAccount(idx, 'username', e.target.value)}
                        className="form-input"
                        style={{ flex: 1.2, padding: '0.5rem' }}
                      />
                      <input
                        type="password"
                        placeholder="密码"
                        value={acc.password}
                        onChange={(e) => updateAccount(idx, 'password', e.target.value)}
                        className="form-input"
                        style={{ flex: 1.2, padding: '0.5rem' }}
                      />
                      <button
                        type="button"
                        onClick={() => removeAccount(idx)}
                        className="btn btn-danger"
                        style={{ padding: '0.5rem' }}
                      >
                        删除
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Knowledge Base / Context Injections */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', height: '100%' }}>
              <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '0.25rem' }}>背景知识库 (推荐注入)</h3>

              <DocumentUploader
                label="PRD / 需求文档"
                value={prd}
                onChange={setPrd}
                placeholder="粘贴产品需求文档内容，以便 AI 深入理解您的业务规则与必选校验..."
              />

              <DocumentUploader
                label="接口文档 (Swagger / API Docs)"
                value={swagger}
                onChange={setSwagger}
                placeholder="粘贴 Swagger JSON 文本，指导 AI 验证底层 API 及其边界用例..."
                allowUrlFetch={true}
              />

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">UI 交互原型链接 (Prototype URL)</label>
                <input
                  type="url"
                  value={prototypeUrl}
                  onChange={(e) => setPrototypeUrl(e.target.value)}
                  placeholder="Figma / 蓝湖原型页面地址..."
                  className="form-input"
                />
              </div>

              <DocumentUploader
                label="UI 原型源码 / 页面文本"
                value={prototypeSource}
                onChange={setPrototypeSource}
                placeholder="粘贴蓝湖源码、Axure 导出页面文本，或上传 HTML/Markdown，用于离线理解页面字段、按钮与流程..."
              />

              <DocumentUploader
                label="技术实现逻辑 / 架构文档"
                value={techDoc}
                onChange={setTechDoc}
                placeholder="简述系统架构设计或关键逻辑实现，便于 AI 理解潜在缺陷高发区域..."
              />

              <DocumentUploader
                label="版本变更日志 (Changelog)"
                value={changelog}
                onChange={setChangelog}
                placeholder="在此说明本次发版的修复内容和改动点，指导 AI 更有针对性地进行回归测试..."
              />
            </div>
          </div>
        </div>

        {/* Bottom Panel: Rules, Focus Areas & Submit */}
        <div className="glass-panel" style={{ marginBottom: '2rem' }}>
          <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', marginBottom: '1.5rem' }}>测试规则与约束</h3>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: '1.5rem' }}>
            <div className="form-group">
              <label className="form-label">自定义测试规则 (Rules)</label>
              <textarea
                value={rules}
                onChange={(e) => setRules(e.target.value)}
                placeholder="例如：禁止使用 evaluate_js；限制单次流程提交间隔；遇到高风险断言需转人工复核..."
                rows={4}
                className="form-textarea"
              />
            </div>

            <div className="form-group">
              <label className="form-label">核心关注领域 (Focus Areas)</label>
              <textarea
                value={focusAreas}
                onChange={(e) => setFocusAreas(e.target.value)}
                placeholder="例如：重点测试订单支付流程的异常捕获与提示；表单的重复提交拦截..."
                rows={4}
                className="form-textarea"
              />
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '3rem' }}>
          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary"
            style={{ width: '100%', maxWidth: '400px', padding: '1rem', fontSize: '1.1rem', borderRadius: '10px' }}
          >
            {loading ? '正在分析背景并创建任务...' : '🚀 开始自动化测试'}
          </button>
        </div>
      </form>
    </div>
  );
}
