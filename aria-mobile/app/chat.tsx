import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Vibration,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { StackNavigationProp } from '@react-navigation/stack';
import * as Haptics from 'expo-haptics';
import * as Speech from 'expo-speech';
import { useARIA } from '../hooks/useARIA';
import { MessageBubble } from '../components/MessageBubble';
import { VoiceButton } from '../components/VoiceButton';
import { OrbAnimation } from '../components/OrbAnimation';
import { RootStackParamList } from '../App';

type Message = { id: string; role: 'user' | 'assistant'; text: string; streaming?: boolean };

function toSpeechText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#*_`>\[\]()]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 600);
}

type Props = {
  navigation: StackNavigationProp<RootStackParamList, 'Chat'>;
};

export default function ChatScreen({ navigation }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const flatRef = useRef<FlatList>(null);
  const aria = useARIA();
  const insets = useSafeAreaInsets();

  useEffect(() => {
    aria.warmup();
    aria.getBaseUrl().then(async (url) => {
      try {
        const res = await fetch(`${url}/ping`, { method: 'GET' });
        setConnected(res.ok);
      } catch {
        setConnected(false);
      }
    });
    return () => { Speech.stop(); };
  }, []);

  const scrollToEnd = () => {
    setTimeout(() => flatRef.current?.scrollToEnd({ animated: true }), 100);
  };

  const send = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || loading) return;
    setInput('');
    setLoading(true);
    Vibration.vibrate(30);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);

    const userId = Date.now().toString();
    const ariaId = (Date.now() + 1).toString();

    setMessages((prev) => [
      ...prev,
      { id: userId, role: 'user', text },
      { id: ariaId, role: 'assistant', text: '', streaming: true },
    ]);
    scrollToEnd();

    try {
      const full = await aria.askStream(text, (token) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === ariaId ? { ...m, text: m.text + token } : m)),
        );
        flatRef.current?.scrollToEnd({ animated: false });
      });
      setConnected(true);
      const spoken = toSpeechText(full);
      if (spoken) Speech.speak(spoken, { language: 'fr-FR', rate: 1.0 });
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === ariaId ? { ...m, text: 'Erreur de connexion au PC', streaming: false } : m,
        ),
      );
      setConnected(false);
    }

    setMessages((prev) =>
      prev.map((m) => (m.id === ariaId ? { ...m, streaming: false } : m)),
    );
    setLoading(false);
    Vibration.vibrate(20);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
  };

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await aria.clearHistory();
      setMessages([]);
    } catch {
      /* ignore */
    }
    setRefreshing(false);
  }, [aria]);

  const renderMessage = ({ item }: { item: Message }) => (
    <MessageBubble role={item.role} text={item.text} streaming={item.streaming} />
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <View style={[styles.header, { paddingTop: insets.top + 8 }]}>
        <OrbAnimation active={loading} size={28} />
        <Text style={styles.headerTitle}>A R I A</Text>
        <View style={styles.headerRight}>
          <View style={[styles.dot, { backgroundColor: connected ? '#4ADE80' : '#F87171' }]} />
          <TouchableOpacity onPress={() => navigation.navigate('Settings')}>
            <Text style={styles.settingsBtn}>⚙</Text>
          </TouchableOpacity>
        </View>
      </View>

      <FlatList
        ref={flatRef}
        data={messages}
        renderItem={renderMessage}
        keyExtractor={(m) => m.id}
        contentContainerStyle={styles.messages}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#6C8EFF"
            title="Nouvelle conversation"
          />
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyIcon}>◎</Text>
            <Text style={styles.emptyText}>Comment puis-je t'aider ?</Text>
            <Text style={styles.emptyHint}>Toutes les actions s'exécutent sur ton PC</Text>
          </View>
        }
      />

      <View style={[styles.inputBar, { paddingBottom: insets.bottom + 8 }]}>
        <VoiceButton
          transcribe={aria.transcribeAudio}
          onVoiceMessage={(text) => send(text)}
          disabled={loading}
        />
        <TextInput
          style={styles.textInput}
          value={input}
          onChangeText={setInput}
          placeholder="Écris un message..."
          placeholderTextColor="#55555F"
          multiline
          maxLength={2000}
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!input.trim() || loading) && styles.sendBtnDisabled]}
          onPress={() => send()}
          disabled={!input.trim() || loading}
        >
          {loading ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Text style={styles.sendIcon}>➤</Text>
          )}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0C0C0F' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.06)',
  },
  headerTitle: { fontSize: 16, fontWeight: '700', color: '#F1F1F3', letterSpacing: 5, flex: 1, textAlign: 'center' },
  headerRight: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  settingsBtn: { fontSize: 20, color: '#8B8B9E' },
  dot: { width: 8, height: 8, borderRadius: 4 },
  messages: { padding: 16, gap: 12, flexGrow: 1 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingTop: 80, gap: 8 },
  emptyIcon: { fontSize: 36, color: '#55555F' },
  emptyText: { fontSize: 15, color: '#8B8B9E' },
  emptyHint: { fontSize: 12, color: '#55555F' },
  inputBar: {
    flexDirection: 'row',
    padding: 12,
    paddingHorizontal: 16,
    gap: 10,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.06)',
    alignItems: 'flex-end',
  },
  textInput: {
    flex: 1,
    backgroundColor: '#17171E',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.06)',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: '#F1F1F3',
    fontSize: 15,
    maxHeight: 100,
  },
  sendBtn: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#6C8EFF',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnDisabled: { backgroundColor: '#17171E' },
  sendIcon: { color: '#fff', fontSize: 18 },
});
