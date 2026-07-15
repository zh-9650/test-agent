import { useEffect, useState } from 'react';

interface MemoryItem {
  id: number;
  scope_type: string;
  scope_value: string;
  memory_key: string;
  memory_value: string;
  created_at: string;
  updated_at: string;
}

export default function MemoryManager() {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<MemoryItem>>({});
  const [isCreating, setIsCreating] = useState(false);

  const fetchMemories = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/memory');
      const data = await res.json();
      setMemories(data.memories || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    fetch('/api/memory')
      .then((res) => res.json())
      .then((data) => {
        if (active) setMemories(data.memories || []);
      })
      .catch((error) => console.error(error))
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除这条记忆规则吗？这将无法恢复。')) return;
    try {
      await fetch(`/api/memory/${id}`, { method: 'DELETE' });
      fetchMemories();
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveEdit = async (id: number) => {
    try {
      await fetch(`/api/memory/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm),
      });
      setEditingId(null);
      fetchMemories();
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreate = async () => {
    try {
      await fetch('/api/memory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm),
      });
      setIsCreating(false);
      setEditForm({});
      fetchMemories();
    } catch (e) {
      console.error(e);
    }
  };

  const startEdit = (mem: MemoryItem) => {
    setEditingId(mem.id);
    setEditForm(mem);
  };

  const startCreate = () => {
    setIsCreating(true);
    setEditForm({ scope_type: 'global', scope_value: '*', memory_key: '', memory_value: '' });
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '0 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      
      {/* Title Header */}
      <div className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '1.8rem' }}>AI 知识库 / 记忆管理</h1>
          <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)' }}>
            维护 AI 智能体在页面探索、设计中使用的全局或域级经验（如特定验证码规则、绕过规则等）。
          </p>
        </div>
        {!isCreating && (
          <button onClick={startCreate} className="btn btn-primary">
            + 添加记忆知识
          </button>
        )}
      </div>

      {/* Add New Memory Form Panel */}
      {isCreating && (
        <div className="glass-panel" style={{ borderLeft: '4px solid var(--accent-blue)' }}>
          <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem', marginBottom: '1.25rem' }}>
            新增知识规则
          </h3>
          
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', marginBottom: '1rem' }}>
            <div className="form-group">
              <label className="form-label">作用域类型 (Scope)</label>
              <select 
                value={editForm.scope_type} 
                onChange={e => setEditForm({...editForm, scope_type: e.target.value})}
                className="form-select"
              >
                <option value="global">Global (全局通用)</option>
                <option value="domain">Domain (特定系统隔离)</option>
              </select>
            </div>
            
            <div className="form-group">
              <label className="form-label">作用域目标 (URL 或 Domain)</label>
              <input 
                value={editForm.scope_value} 
                onChange={e => setEditForm({...editForm, scope_value: e.target.value})} 
                placeholder="如 example.com 或 * 表示所有"
                className="form-input" 
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">知识标识 (Key)</label>
            <input 
              value={editForm.memory_key} 
              onChange={e => setEditForm({...editForm, memory_key: e.target.value})} 
              placeholder="如 input_text.captcha.bypass_rule (建议小写点分规范)"
              className="form-input" 
            />
          </div>

          <div className="form-group">
            <label className="form-label">详细规则内容 (Value / Knowledge)</label>
            <textarea 
              value={editForm.memory_value} 
              onChange={e => setEditForm({...editForm, memory_value: e.target.value})} 
              placeholder="输入该场景下 AI 需遵守的具体经验描述..."
              rows={4}
              className="form-textarea" 
            />
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.25rem' }}>
            <button onClick={handleCreate} className="btn btn-primary" style={{ padding: '0.5rem 1.5rem' }}>
              保存知识
            </button>
            <button onClick={() => setIsCreating(false)} className="btn btn-secondary">
              取消
            </button>
          </div>
        </div>
      )}

      {/* Memories Table List */}
      <div className="glass-panel" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <p style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>正在载入知识库内容...</p>
        ) : (
          <div className="table-container" style={{ border: 'none', borderRadius: 0, background: 'transparent' }}>
            <table className="custom-table">
              <thead>
                <tr>
                  <th style={{ width: '8%' }}>ID</th>
                  <th style={{ width: '12%' }}>Scope 类型</th>
                  <th style={{ width: '15%' }}>作用目标 (Domain)</th>
                  <th style={{ width: '20%' }}>知识标识 (Key)</th>
                  <th style={{ width: '30%' }}>详细内容描述 (Value)</th>
                  <th style={{ width: '15%', textAlign: 'center' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {memories.map(mem => (
                  <tr key={mem.id}>
                    {editingId === mem.id ? (
                      <>
                        <td>#{mem.id}</td>
                        <td>
                          <select 
                            value={editForm.scope_type} 
                            onChange={e => setEditForm({...editForm, scope_type: e.target.value})}
                            className="form-select"
                            style={{ padding: '0.35rem 0.5rem', fontSize: '0.85rem' }}
                          >
                            <option value="global">Global</option>
                            <option value="domain">Domain</option>
                          </select>
                        </td>
                        <td>
                          <input 
                            value={editForm.scope_value} 
                            onChange={e => setEditForm({...editForm, scope_value: e.target.value})} 
                            className="form-input"
                            style={{ padding: '0.35rem 0.5rem', fontSize: '0.85rem' }}
                          />
                        </td>
                        <td>
                          <input 
                            value={editForm.memory_key} 
                            onChange={e => setEditForm({...editForm, memory_key: e.target.value})} 
                            className="form-input"
                            style={{ padding: '0.35rem 0.5rem', fontSize: '0.85rem' }}
                          />
                        </td>
                        <td>
                          <textarea 
                            value={editForm.memory_value} 
                            onChange={e => setEditForm({...editForm, memory_value: e.target.value})} 
                            className="form-textarea"
                            style={{ padding: '0.35rem 0.5rem', fontSize: '0.85rem', minHeight: '60px' }}
                          />
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
                            <button onClick={() => handleSaveEdit(mem.id)} className="btn btn-success" style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}>
                              保存
                            </button>
                            <button onClick={() => setEditingId(null)} className="btn btn-secondary" style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}>
                              取消
                            </button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>#{mem.id}</td>
                        <td>
                          <span className={`badge ${mem.scope_type === 'global' ? 'badge-passed' : 'badge-review'}`} style={{ fontSize: '0.7rem' }}>
                            {mem.scope_type === 'global' ? '全局通用' : '独立域'}
                          </span>
                        </td>
                        <td><code>{mem.scope_value}</code></td>
                        <td><strong style={{ fontFamily: 'var(--font-mono)' }}>{mem.memory_key}</strong></td>
                        <td style={{ whiteSpace: 'pre-wrap', lineHeight: '1.5', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                          {mem.memory_value}
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
                            <button onClick={() => startEdit(mem)} className="btn btn-secondary" style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}>
                              编辑
                            </button>
                            <button onClick={() => handleDelete(mem.id)} className="btn btn-danger" style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}>
                              删除
                            </button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                ))}

                {memories.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                      📂 暂无记忆规则。添加测试特定知识可指引智能体更聪明地操作。
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
