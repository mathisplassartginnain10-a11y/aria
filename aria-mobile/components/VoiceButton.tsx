import React, { useRef, useState } from 'react';
import { TouchableOpacity, Text, StyleSheet, Alert, ActivityIndicator } from 'react-native';
import { Audio } from 'expo-av';
import * as Haptics from 'expo-haptics';

type Props = {
  onVoiceMessage: (text: string) => void;
  transcribe: (uri: string) => Promise<string>;
  disabled?: boolean;
};

export function VoiceButton({ onVoiceMessage, transcribe, disabled }: Props) {
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const recordingRef = useRef<Audio.Recording | null>(null);

  const startRecording = async () => {
    if (disabled || processing) return;
    try {
      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('Microphone', 'Autorise le micro pour la saisie vocale.');
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const { recording: rec } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recordingRef.current = rec;
      setRecording(true);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch {
      Alert.alert('Erreur', 'Impossible de démarrer l\'enregistrement.');
    }
  };

  const stopRecording = async () => {
    const rec = recordingRef.current;
    if (!rec || processing) return;
    setRecording(false);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await rec.stopAndUnloadAsync();
      const uri = rec.getURI();
      recordingRef.current = null;
      if (!uri) return;

      setProcessing(true);
      const text = await transcribe(uri);
      if (text.trim()) {
        onVoiceMessage(text.trim());
      } else {
        Alert.alert('ARIA', 'Je n\'ai rien entendu — réessaie.');
      }
    } catch {
      Alert.alert('Erreur', 'Transcription impossible. Vérifie la connexion au PC.');
    } finally {
      setProcessing(false);
    }
  };

  const busy = disabled || processing;

  return (
    <TouchableOpacity
      style={[styles.btn, recording && styles.btnActive, busy && styles.btnDisabled]}
      onPressIn={startRecording}
      onPressOut={stopRecording}
      disabled={busy}
    >
      {processing ? (
        <ActivityIndicator size="small" color="#6C8EFF" />
      ) : (
        <Text style={styles.icon}>{recording ? '⏹' : '🎤'}</Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  btn: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#17171E',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.06)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnActive: {
    backgroundColor: 'rgba(248,113,113,0.15)',
    borderColor: '#F87171',
  },
  btnDisabled: { opacity: 0.5 },
  icon: { fontSize: 20 },
});
