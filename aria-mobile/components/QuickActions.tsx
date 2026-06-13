import React from 'react';
import { ScrollView, TouchableOpacity, Text, StyleSheet } from 'react-native';

export type PresetChip = { key: string; label: string; icon: string; active?: boolean };

type ExtraAction = { label: string; text: string };

const EXTRAS: ExtraAction[] = [
  { label: '🌤 Météo', text: 'Quelle est la météo ?' },
  { label: '🔊 Vol 50', text: 'Mets le volume à 50' },
  { label: '🎵 Spotify', text: 'Lance Spotify' },
  { label: '💻 Cursor', text: 'Lance Cursor' },
];

type Props = {
  presets: PresetChip[];
  onPreset: (key: string) => void;
  onAction: (text: string) => void;
  disabled?: boolean;
};

export function QuickActions({ presets, onPreset, onAction, disabled }: Props) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      keyboardShouldPersistTaps="handled"
    >
      {presets.map((p) => (
        <TouchableOpacity
          key={p.key}
          style={[styles.chip, p.active && styles.chipActive, disabled && styles.chipDisabled]}
          onPress={() => onPreset(p.key)}
          disabled={disabled}
        >
          <Text style={[styles.chipText, p.active && styles.chipTextActive]}>
            {p.icon} {p.label}
          </Text>
        </TouchableOpacity>
      ))}
      {EXTRAS.map((a) => (
        <TouchableOpacity
          key={a.label}
          style={[styles.chip, disabled && styles.chipDisabled]}
          onPress={() => onAction(a.text)}
          disabled={disabled}
        >
          <Text style={styles.chipText}>{a.label}</Text>
        </TouchableOpacity>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 16, paddingVertical: 8, gap: 8 },
  chip: {
    backgroundColor: '#17171E',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: {
    backgroundColor: 'rgba(108,142,255,0.15)',
    borderColor: 'rgba(108,142,255,0.4)',
  },
  chipDisabled: { opacity: 0.4 },
  chipText: { color: '#E8E8F0', fontSize: 13 },
  chipTextActive: { color: '#6C8EFF' },
});
