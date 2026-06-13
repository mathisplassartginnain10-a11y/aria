import React, { useState, useEffect } from 'react';
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

type Props = {
  navigation: StackNavigationProp<RootStackParamList, 'Pin'>;
};

export default function PinScreen({ navigation }: Props) {
  const [ip, setIp] = useState('');
  const [pin, setPin] = useState('');
  const [step, setStep] = useState<'ip' | 'pin'>('ip');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const aria = useARIA();

  useEffect(() => {
    AsyncStorage.getItem('aria_token').then((token) => {
      if (token) navigation.replace('Chat');
    });
    AsyncStorage.getItem('aria_ip').then((savedIp) => {
      if (savedIp) setIp(savedIp);
    });
  }, [navigation]);

  const handleIpNext = async () => {
    setLoading(true);
    setError('');
    try {
      await aria.ping(ip);
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

  return (
    <View style={styles.container}>
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
            autoFocus
          />
          <Text style={styles.hint}>Lance ARIA sur ton PC pour voir l'IP</Text>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <TouchableOpacity style={styles.btn} onPress={handleIpNext} disabled={loading || !ip}>
            {loading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.btnText}>Connecter →</Text>
            )}
          </TouchableOpacity>
        </>
      ) : (
        <>
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
  hint: { fontSize: 11, color: '#555', marginBottom: 24, alignSelf: 'flex-start' },
  error: { color: '#F87171', fontSize: 12, marginBottom: 12 },
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
