import React, { useEffect, useState } from 'react';

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
  const [loading, setLoading] = useState(false);

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
    fetchMemories();
  }, []);

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除这条记忆吗？')) return;
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
      await fetch('http://localhost:8000/api/memory', {
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
    <div style={{ padding: '2rem' }}>
      <h2>AI 知识库 / 记忆管理</h2>
      <p>管理 AI 在测试过程中学习到的系统经验与特定操作规则。</p>
      
      <button onClick={startCreate} style={{ marginBottom: '1rem', padding: '0.5rem 1rem', background: '#4CAF50', color: 'white', border: 'none', cursor: 'pointer' }}>
        + 添加记忆
      </button>

      {isCreating && (
        <div style={{ padding: '1rem', border: '1px solid #ccc', marginBottom: '1rem' }}>
          <h3>新增记忆</h3>
          <div style={{ marginBottom: '8px' }}>
            <label>作用域类型: </label>
            <select value={editForm.scope_type} onChange={e => setEditForm({...editForm, scope_type: e.target.value})}>
              <option value="global">Global (全局通用)</option>
              <option value="domain">Domain (系统隔离)</option>
            </select>
          </div>
          <div style={{ marginBottom: '8px' }}>
            <label>作用域目标 (URL/Domain 或 *): </label>
            <input value={editForm.scope_value} onChange={e => setEditForm({...editForm, scope_value: e.target.value})} style={{ width: '300px' }} />
          </div>
          <div style={{ marginBottom: '8px' }}>
            <label>记忆标识 (Key): </label>
            <input value={editForm.memory_key} onChange={e => setEditForm({...editForm, memory_key: e.target.value})} style={{ width: '100%' }} />
          </div>
          <div style={{ marginBottom: '8px' }}>
            <label>详细知识 (Value): </label>
            <textarea value={editForm.memory_value} onChange={e => setEditForm({...editForm, memory_value: e.target.value})} style={{ width: '100%', height: '80px' }} />
          </div>
          <button onClick={handleCreate} style={{ marginRight: '8px' }}>保存</button>
          <button onClick={() => setIsCreating(false)}>取消</button>
        </div>
      )}

      {loading ? <p>加载中...</p> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }}>
          <thead>
            <tr style={{ background: '#f5f5f5', textAlign: 'left' }}>
              <th style={{ padding: '8px', borderBottom: '1px solid #ddd', width: '50px' }}>ID</th>
              <th style={{ padding: '8px', borderBottom: '1px solid #ddd', width: '100px' }}>Scope</th>
              <th style={{ padding: '8px', borderBottom: '1px solid #ddd', width: '150px' }}>Target</th>
              <th style={{ padding: '8px', borderBottom: '1px solid #ddd', width: '150px' }}>Key</th>
              <th style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>Value (Knowledge)</th>
              <th style={{ padding: '8px', borderBottom: '1px solid #ddd', width: '120px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {memories.map(mem => (
              <tr key={mem.id}>
                {editingId === mem.id ? (
                  <>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>{mem.id}</td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>
                      <select value={editForm.scope_type} onChange={e => setEditForm({...editForm, scope_type: e.target.value})}>
                        <option value="global">Global</option>
                        <option value="domain">Domain</option>
                      </select>
                    </td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>
                      <input value={editForm.scope_value} onChange={e => setEditForm({...editForm, scope_value: e.target.value})} style={{ width: '100%' }} />
                    </td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>
                      <input value={editForm.memory_key} onChange={e => setEditForm({...editForm, memory_key: e.target.value})} style={{ width: '100%' }} />
                    </td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>
                      <textarea value={editForm.memory_value} onChange={e => setEditForm({...editForm, memory_value: e.target.value})} style={{ width: '100%', minHeight: '60px' }} />
                    </td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>
                      <button onClick={() => handleSaveEdit(mem.id)} style={{ marginRight: '4px' }}>保存</button>
                      <button onClick={() => setEditingId(null)}>取消</button>
                    </td>
                  </>
                ) : (
                  <>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>{mem.id}</td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>
                      <span style={{ padding: '2px 6px', background: mem.scope_type === 'global' ? '#e3f2fd' : '#fff3e0', borderRadius: '4px', fontSize: '0.85em' }}>
                        {mem.scope_type}
                      </span>
                    </td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>{mem.scope_value}</td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}><strong>{mem.memory_key}</strong></td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd', whiteSpace: 'pre-wrap', lineHeight: '1.4' }}>{mem.memory_value}</td>
                    <td style={{ padding: '8px', borderBottom: '1px solid #ddd' }}>
                      <button onClick={() => startEdit(mem)} style={{ marginRight: '8px' }}>编辑</button>
                      <button onClick={() => handleDelete(mem.id)} style={{ color: 'red' }}>删除</button>
                    </td>
                  </>
                )}
              </tr>
            ))}
            {memories.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: '1rem', textAlign: 'center', color: '#666' }}>暂无记忆数据</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
