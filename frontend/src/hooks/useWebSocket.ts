import { useEffect, useRef, useState, useCallback } from 'react';
import type { WSMessage } from '../types';

export function useWebSocket(taskId: string | number | undefined) {
  const [messages, setMessages] = useState<WSMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!taskId) return;

    const ws = new WebSocket(`ws://localhost:8001/ws/tasks/${taskId}`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data) as WSMessage;
        setMessages((prev) => [...prev, msg]);
      } catch (e) {
        console.error('WS parse error:', e);
      }
    };

    return () => {
      ws.close();
    };
  }, [taskId]);

  const sendStop = useCallback(() => {
    wsRef.current?.send('stop');
  }, []);

  return { messages, connected, sendStop };
}
