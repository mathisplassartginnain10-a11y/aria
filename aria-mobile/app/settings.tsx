import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { StackNavigationProp } from '@react-navigation/stack';
import { RootStackParamList } from '../App';

type Props = {
  navigation: StackNavigationProp<RootStackParamList, 'Settings'>;
};

export default function SettingsScreen({ navigation }: Props) {
  const insets = useSafeAreaInsets();
  const [ip, setIp] = useState('');
  const [port, setPort] = useState('5000');

  useEffect(() => {
    AsyncStorage.multiGet(['aria_ip', 'aria_port']).then((pairs) => {
      const map = Object.fromEntries(pairs);
      if (map.aria_ip) setIp(map.aria_ip);
      if (map.aria_port) setPort(map.aria_port);
    });
  }, []);

  const save = async () => {
    await AsyncStorage.setItem('aria_ip', ip.trim());
    await AsyncStorage.setItem('aria_port', port.trim() || '5000');
    Alert.alert('Enregistré', 'Configuration mise à jour.');
  };

  const logout = async () => {
    await AsyncStorage.multiRemove(['aria_token', 'aria_ip', 'aria_port']);
    navigation.reset({ index: 0, routes: [{ name: 'Pin' }] });
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top + 16 }]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={styles.back}>← Retour</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Réglages</Text>
        <View style={{ width: 60 }} />
      </View>

      <Text style={styles.label}>Adresse IP du PC</Text>
      <TextInput
        style={styles.input}
        value={ip}
        onChangeText={setIp}
        placeholder="192.168.1.XX"
        placeholderTextColor="#555"
        keyboardType="numeric"
      />

      <Text style={styles.label}>Port</Text>
      <TextInput
        style={styles.input}
        value={port}
        onChangeText={setPort}
        placeholder="5000"
        placeholderTextColor="#555"
        keyboardType="numeric"
      />

      <TouchableOpacity style={styles.btnPrimary} onPress={save}>
        <Text style={styles.btnText}>Enregistrer</Text>
      </TouchableOpacity>

      <TouchableOpacity style={styles.btnDanger} onPress={logout}>
        <Text style={styles.btnDangerText}>Déconnexion</Text>
      </TouchableOpacity>

      <Text style={styles.footer}>
        L'app mobile envoie les commandes à ARIA sur ton PC.{'\n'}
        Endpoint rapide : /ask/fast · Stream : /ask/stream
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0C0C0F', padding: 24 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 32,
  },
  back: { color: '#6C8EFF', fontSize: 15 },
  title: { fontSize: 18, fontWeight: '600', color: '#F1F1F3' },
  label: { fontSize: 13, color: '#8B8B9E', marginBottom: 8 },
  input: {
    backgroundColor: '#17171E',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    borderRadius: 12,
    padding: 14,
    color: '#F1F1F3',
    fontSize: 16,
    marginBottom: 20,
  },
  btnPrimary: {
    backgroundColor: '#6C8EFF',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  btnText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  btnDanger: {
    marginTop: 16,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(248,113,113,0.4)',
  },
  btnDangerText: { color: '#F87171', fontWeight: '600' },
  footer: { marginTop: 32, fontSize: 12, color: '#55555F', lineHeight: 18, textAlign: 'center' },
});
