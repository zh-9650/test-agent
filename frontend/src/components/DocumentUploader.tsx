import React, { useRef, useState } from 'react';

interface DocumentUploaderProps {
  label: string;
  value: string;
  onChange: (val: string) => void;
  placeholder: string;
  allowUrlFetch?: boolean;
  acceptedFormats?: string;
}

export default function DocumentUploader({
  label,
  value,
  onChange,
  placeholder,
  allowUrlFetch = false,
  acceptedFormats = ".txt,.md,.json,.yaml,.docx"
}: DocumentUploaderProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [url, setUrl] = useState('');

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/utils/parse-doc', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Failed to parse file: ${response.statusText}`);
      }

      const data = await response.json();
      onChange(data.text);
    } catch (err) {
      console.error(err);
      alert('解析文件失败: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleUrlFetch = async () => {
    if (!url.trim()) return;

    setLoading(true);
    try {
      const response = await fetch('/api/utils/fetch-url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url: url.trim() }),
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch URL: ${response.statusText}`);
      }

      const data = await response.json();
      onChange(data.text);
    } catch (err) {
      console.error(err);
      alert('抓取链接失败: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
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
    marginBottom: '0.5rem',
  };

  const buttonStyle: React.CSSProperties = {
    padding: '0.5rem 1rem',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontWeight: 600,
    backgroundColor: '#e0e0e0',
    marginBottom: '0.5rem',
  };

  return (
    <div style={{ marginBottom: '1rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <label style={labelStyle}>{label}</label>
        <div>
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            accept={acceptedFormats}
            onChange={handleFileUpload}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            style={{ ...buttonStyle, backgroundColor: '#f0f0f0' }}
            disabled={loading}
          >
            {loading ? '处理中...' : '📤 上传文件'}
          </button>
        </div>
      </div>

      {allowUrlFetch && (
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="或者输入 Swagger JSON 链接抓取..."
            style={{ ...inputStyle, marginBottom: 0 }}
            disabled={loading}
          />
          <button
            type="button"
            onClick={handleUrlFetch}
            style={{ ...buttonStyle, marginBottom: 0 }}
            disabled={loading || !url.trim()}
          >
            抓取
          </button>
        </div>
      )}

      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={4}
        style={{ ...inputStyle, resize: 'vertical' }}
      />
    </div>
  );
}
