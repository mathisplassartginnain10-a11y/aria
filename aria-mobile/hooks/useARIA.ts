import AsyncStorage from '@react-native-async-storage/async-storage';

const DEFAULT_PORT = '5000';
export const STORAGE_TTS = 'aria_tts_enabled';

export type PingResult = {
  ip: string;
  pc_name?: string;
  local_ip?: string;
  whisper_ready?: boolean;
  ollama_running?: boolean;
};

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

  const getTtsEnabled = async () => {
    const v = await AsyncStorage.getItem(STORAGE_TTS);
    return v !== 'false';
  };

  const setTtsEnabled = async (enabled: boolean) => {
    await AsyncStorage.setItem(STORAGE_TTS, enabled ? 'true' : 'false');
  };

  const pingHost = async (ip: string, port = DEFAULT_PORT, timeoutMs = 1500): Promise<PingResult | null> => {
    try {
      const res = await fetchWithTimeout(`http://${ip}:${port}/ping`, {}, timeoutMs);
      if (!res.ok) return null;
      const data = await res.json();
      if (data?.status === 'ok' && data?.name === 'ARIA') {
        return { ip, ...data };
      }
      return null;
    } catch {
      return null;
    }
  };

  const ping = async (ip: string) => {
    const port = (await AsyncStorage.getItem('aria_port')) || DEFAULT_PORT;
    const result = await pingHost(ip, port, 3000);
    if (!result) throw new Error('PC introuvable');
    return result;
  };

  const scanForPc = async (
    onProgress?: (message: string) => void,
    seedIp?: string,
  ): Promise<PingResult | null> => {
    const port = (await AsyncStorage.getItem('aria_port')) || DEFAULT_PORT;
    const prefixes: string[] = [];

    if (seedIp) {
      const parts = seedIp.trim().split('.');
      if (parts.length >= 3 && parts.every((p) => /^\d+$/.test(p))) {
        prefixes.push(`${parts[0]}.${parts[1]}.${parts[2]}`);
      }
    }
    for (const p of ['192.168.1', '192.168.0', '192.168.43', '10.0.0', '172.16.0']) {
      if (!prefixes.includes(p)) prefixes.push(p);
    }

    for (const prefix of prefixes) {
      onProgress?.(`Recherche sur ${prefix}.x…`);
      const hosts = Array.from({ length: 254 }, (_, i) => `${prefix}.${i + 1}`);
      for (let i = 0; i < hosts.length; i += 30) {
        const batch = hosts.slice(i, i + 30);
        const results = await Promise.all(batch.map((host) => pingHost(host, port, 1200)));
        const found = results.find((r) => r !== null);
        if (found) return found;
      }
    }
    return null;
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

  const askStream = async (text: string, onToken: (t: string) => void): Promise<string> => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    const res = await fetchWithTimeout(`${base}/ask/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token || '' },
      body: JSON.stringify({ text }),
    }, 90000);

    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    if (!reader) return '';

    let full = '';
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
            if (data.token) {
              full += data.token;
              onToken(data.token);
            }
            if (data.done) return full;
          } catch {
            /* ignore malformed chunks */
          }
        }
      }
    }
    return full;
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

  const transcribeAudio = async (uri: string): Promise<string> => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    const ext = uri.split('.').pop()?.split('?')[0] || 'm4a';
    const mime = ext === 'wav' ? 'audio/wav' : ext === 'mp4' ? 'audio/mp4' : 'audio/m4a';
    const form = new FormData();
    form.append('audio', { uri, type: mime, name: `recording.${ext}` } as unknown as Blob);

    const res = await fetchWithTimeout(`${base}/transcribe`, {
      method: 'POST',
      headers: { 'X-Token': token || '' },
      body: form,
    }, 90000);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Transcription échouée');
    return data.text || '';
  };

  const getPresets = async () => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    const res = await fetchWithTimeout(`${base}/presets`, {
      headers: { 'X-Token': token || '' },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.presets || [];
  };

  const activatePreset = async (name: string) => {
    const [base, token] = await Promise.all([getBaseUrl(), getToken()]);
    const res = await fetchWithTimeout(`${base}/presets/${encodeURIComponent(name)}/activate`, {
      method: 'POST',
      headers: { 'X-Token': token || '' },
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Preset échoué');
    return data.result as string;
  };

  return {
    ping, pingHost, scanForPc, auth, askFast, askStream, warmup, clearHistory,
    transcribeAudio, getPresets, activatePreset, getTtsEnabled, setTtsEnabled,
    getBaseUrl, getToken,
  };
}
