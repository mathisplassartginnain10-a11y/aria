import AsyncStorage from '@react-native-async-storage/async-storage';

const DEFAULT_PORT = '5000';

function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(timer));
}

export function useARIA() {
  const getBaseUrl = async () => {
    const ip = await AsyncStorage.getItem('aria_ip');
    const port = (await AsyncStorage.getItem('aria_port')) || DEFAULT_PORT;
    return `http://${ip}:${port}`;
  };

  const getToken = async () => AsyncStorage.getItem('aria_token');

  const ping = async (ip: string) => {
    const port = (await AsyncStorage.getItem('aria_port')) || DEFAULT_PORT;
    const res = await fetchWithTimeout(`http://${ip}:${port}/ping`, {}, 3000);
    return res.json();
  };

  const auth = async (ip: string, pin: string) => {
    const port = (await AsyncStorage.getItem('aria_port')) || DEFAULT_PORT;
    const res = await fetchWithTimeout(`http://${ip}:${port}/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin }),
    });
    const data = await res.json();
    if (data.token) {
      await AsyncStorage.setItem('aria_token', data.token);
      await AsyncStorage.setItem('aria_ip', ip);
    }
    return data;
  };

  const askFast = async (text: string) => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    const res = await fetchWithTimeout(`${base}/ask/fast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token || '' },
      body: JSON.stringify({ text }),
    });
    return res.json();
  };

  const askStream = async (text: string, onToken: (t: string) => void) => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    const res = await fetchWithTimeout(`${base}/ask/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token || '' },
      body: JSON.stringify({ text }),
    }, 90000);

    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    if (!reader) return;

    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.token) onToken(data.token);
            if (data.done) return;
          } catch {
            /* ignore malformed chunks */
          }
        }
      }
    }
  };

  const warmup = async () => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    fetchWithTimeout(`${base}/warmup`, {
      method: 'POST',
      headers: { 'X-Token': token || '' },
    }, 5000).catch(() => {});
  };

  const clearHistory = async () => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    await fetchWithTimeout(`${base}/history/clear`, {
      method: 'POST',
      headers: { 'X-Token': token || '' },
    });
  };

  return { ping, auth, askFast, askStream, warmup, clearHistory, getBaseUrl, getToken };
}
