import React, { useRef, useState } from 'react';
import { TouchableOpacity, Text, StyleSheet, Alert } from 'react-native';
import { Audio } from 'expo-av';
import * as Haptics from 'expo-haptics';

type Props = {
  onTranscript: (text: string) => void;
  disabled?: boolean;
};

export function VoiceButton({ onTranscript, disabled }: Props) {
  const [recording, setRecording] = useState(false);
  const recordingRef = useRef<Audio.Recording | null>(null);

  const startRecording = async () => {
    if (disabled) return;
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
    if (!rec) return;
    setRecording(false);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await rec.stopAndUnloadAsync();
      const uri = rec.getURI();
      recordingRef.current = null;
      if (uri) {
        // STT côté PC — pour l'instant placeholder local
        onTranscript('[Message vocal enregistré — transcription à venir]');
      }
    } catch {
      recordingRef.current = null;
    }
  };

  return (
    <TouchableOpacity
      style={[styles.btn, recording && styles.btnActive, disabled && styles.btnDisabled]}
      onPressIn={startRecording}
      onPressOut={stopRecording}
      disabled={disabled}
    >
      <Text style={styles.icon}>{recording ? '⏹' : '🎤'}</Text>
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
  btnDisabled: { opacity: 0.4 },
  icon: { fontSize: 20 },
});
