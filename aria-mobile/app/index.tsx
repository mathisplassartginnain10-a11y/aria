import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Vibration,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { StackNavigationProp } from '@react-navigation/stack';
import { useARIA } from '../hooks/useARIA';
import { RootStackParamList } from '../App';
import QrScanner from '../components/QrScanner';

type Props = {
  navigation: StackNavigationProp<RootStackParamList, 'Pin'>;
};

type PcInfo = { pc_name?: string; local_ip?: string; whisper_ready?: boolean };

export default function PinScreen({ navigation }: Props) {
  const [ip, setIp] = useState('');
  const [pin, setPin] = useState('');
  const [step, setStep] = useState<'ip' | 'pin'>('ip');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pcInfo, setPcInfo] = useState<PcInfo | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState('');
  const [showQr, setShowQr] = useState(false);
  const autoScanDone = useRef(false);
  const aria = useARIA();
  const ariaRef = useRef(aria);
  ariaRef.current = aria;

  useEffect(() => {
    let cancelled = false;

    AsyncStorage.getItem('aria_token').then((token) => {
      if (token) navigation.replace('Chat');
    });

    AsyncStorage.getItem('aria_ip').then(async (savedIp) => {
      if (savedIp) {
        setIp(savedIp);
        return;
      }
      if (autoScanDone.current || cancelled) return;
      autoScanDone.current = true;
      setScanning(true);
      setScanStatus('Recherche automatique du PC…');
      try {
        const found = await ariaRef.current.scanForPc((msg) => {
          if (!cancelled) setScanStatus(msg);
        });
        if (cancelled) return;
        if (found) {
          setIp(found.ip);
          setPcInfo(found);
          setStep('pin');
          Vibration.vibrate(50);
        }
      } catch {
        /* scan silencieux */
      } finally {
        if (!cancelled) {
          setScanning(false);
          setScanStatus('');
        }
      }
    });

    return () => {
      cancelled = true;
    };
  }, [navigation]);

  const handleIpNext = async () => {
    setLoading(true);
    setError('');
    try {
      const info = await aria.ping(ip);
      setPcInfo(info);
      setStep('pin');
    } catch {
      setError('PC introuvable. Vérifie que ARIA tourne et que tu es sur le même WiFi.');
      Vibration.vibrate(300);
    }
    setLoading(false);
  };

  const handlePinSubmit = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await aria.auth(ip, pin);
      if (result.token) {
        navigation.replace('Chat');
      } else {
        setError('Code incorrect');
        setPin('');
        Vibration.vibrate([100, 50, 100]);
      }
    } catch {
      setError('Erreur de connexion');
    }
    setLoading(false);
  };

  const handleScan = async () => {
    setScanning(true);
    setError('');
    setScanStatus('Démarrage…');
    try {
      const found = await aria.scanForPc(setScanStatus, ip || undefined);
      if (found) {
        setIp(found.ip);
        setPcInfo(found);
        setStep('pin');
        Vibration.vibrate(50);
      } else {
        setError('Aucun PC ARIA trouvé. Lance ARIA sur ton PC (même WiFi).');
        Vibration.vibrate(300);
      }
    } catch {
      setError('Erreur lors du scan réseau.');
    }
    setScanning(false);
    setScanStatus('');
  };

  const handleQrScan = async (data: string) => {
    setShowQr(false);
    setLoading(true);
    setError('');
    try {
      const info = await aria.connectFromQr(data);
      setIp(info.ip);
      setPcInfo(info);
      setStep('pin');
      Vibration.vibrate(50);
    } catch {
      setError('QR invalide ou PC introuvable.');
      Vibration.vibrate(300);
    }
    setLoading(false);
  };

  const busy = loading || scanning;

  return (
    <View style={styles.container}>
      {showQr ? (
        <QrScanner onScan={handleQrScan} onClose={() => setShowQr(false)} />
      ) : null}

      <Text style={styles.logo}>A R I A</Text>
      <Text style={styles.subtitle}>Assistant Personnel</Text>

      {step === 'ip' ? (
        <>
          <Text style={styles.label}>Adresse IP du PC</Text>
          <TextInput
            style={styles.input}
            value={ip}
            onChangeText={setIp}
            placeholder="192.168.1.XX"
            placeholderTextColor="#555"
            keyboardType="numeric"
            autoFocus={!scanning}
          />
          <Text style={styles.hint}>ARIA démarre le serveur mobile automatiquement (même WiFi)</Text>
          {scanStatus ? <Text style={styles.scanStatus}>{scanStatus}</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <TouchableOpacity style={styles.btnScan} onPress={handleScan} disabled={busy}>
            {scanning ? (
              <ActivityIndicator color="#6C8EFF" />
            ) : (
              <Text style={styles.btnScanText}>🔍 Scanner le réseau</Text>
            )}
          </TouchableOpacity>
          <TouchableOpacity style={styles.btnQr} onPress={() => setShowQr(true)} disabled={busy}>
            <Text style={styles.btnQrText}>📷 Scanner le QR du PC</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.btn} onPress={handleIpNext} disabled={busy || !ip}>
            {loading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.btnText}>Connecter →</Text>
            )}
          </TouchableOpacity>
        </>
      ) : (
        <>
          {pcInfo?.pc_name ? (
            <View style={styles.pcBadge}>
              <Text style={styles.pcBadgeText}>🖥 {pcInfo.pc_name}</Text>
              {pcInfo.whisper_ready ? (
                <Text style={styles.pcBadgeSub}>Micro PC prêt</Text>
              ) : null}
            </View>
          ) : null}
          <Text style={styles.label}>Code PIN</Text>
          <TextInput
            style={[styles.input, styles.pinInput]}
            value={pin}
            onChangeText={setPin}
            placeholder="0000"
            placeholderTextColor="#555"
            keyboardType="number-pad"
            maxLength={4}
            secureTextEntry
            autoFocus
          />
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <TouchableOpacity
            style={styles.btn}
            onPress={handlePinSubmit}
            disabled={loading || pin.length < 4}
          >
            {loading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.btnText}>Entrer →</Text>
            )}
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setStep('ip')}>
            <Text style={styles.backLink}>← Changer d'IP</Text>
          </TouchableOpacity>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0C0C0F',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  logo: { fontSize: 28, fontWeight: '700', color: '#F1F1F3', letterSpacing: 8, marginBottom: 6 },
  subtitle: { fontSize: 13, color: '#555', marginBottom: 48 },
  label: { fontSize: 13, color: '#8B8B9E', marginBottom: 8, alignSelf: 'flex-start' },
  input: {
    width: '100%',
    backgroundColor: '#17171E',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    borderRadius: 12,
    padding: 16,
    color: '#F1F1F3',
    fontSize: 16,
    marginBottom: 8,
  },
  pinInput: { letterSpacing: 12, textAlign: 'center', fontSize: 24 },
  pcBadge: {
    width: '100%',
    backgroundColor: 'rgba(108,142,255,0.08)',
    borderWidth: 1,
    borderColor: 'rgba(108,142,255,0.2)',
    borderRadius: 12,
    padding: 14,
    marginBottom: 20,
    alignItems: 'center',
  },
  pcBadgeText: { color: '#F1F1F3', fontSize: 14, fontWeight: '600' },
  pcBadgeSub: { color: '#6C8EFF', fontSize: 11, marginTop: 4 },
  hint: { fontSize: 11, color: '#555', marginBottom: 12, alignSelf: 'flex-start' },
  scanStatus: { fontSize: 12, color: '#6C8EFF', marginBottom: 12, alignSelf: 'flex-start' },
  error: { color: '#F87171', fontSize: 12, marginBottom: 12 },
  btnScan: {
    width: '100%',
    backgroundColor: 'rgba(108,142,255,0.1)',
    borderWidth: 1,
    borderColor: 'rgba(108,142,255,0.3)',
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
    marginBottom: 10,
  },
  btnScanText: { color: '#6C8EFF', fontWeight: '600', fontSize: 14 },
  btnQr: {
    width: '100%',
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
    marginBottom: 10,
  },
  btnQrText: { color: '#8B8B9E', fontWeight: '600', fontSize: 14 },
  btn: {
    width: '100%',
    backgroundColor: '#6C8EFF',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  btnText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  backLink: { color: '#555', marginTop: 16, fontSize: 13 },
});
