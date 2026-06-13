import React from 'react';
import { ScrollView, TouchableOpacity, Text, StyleSheet } from 'react-native';

type Action = { label: string; text: string };

const ACTIONS: Action[] = [
  { label: '🌤 Météo', text: 'Quelle est la météo ?' },
  { label: '✈ Vol', text: 'Active le preset vol' },
  { label: '🎮 Gaming', text: 'Active le preset gaming' },
  { label: '📚 Étude', text: 'Active le preset étude' },
  { label: '🌙 Nuit', text: 'Active le preset nuit' },
  { label: '🔊 Vol 50', text: 'Mets le volume à 50' },
  { label: '🎵 Spotify', text: 'Lance Spotify' },
  { label: '💻 Cursor', text: 'Lance Cursor' },
];

type Props = {
  onAction: (text: string) => void;
  disabled?: boolean;
};

export function QuickActions({ onAction, disabled }: Props) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      keyboardShouldPersistTaps="handled"
    >
      {ACTIONS.map((a) => (
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
  chipDisabled: { opacity: 0.4 },
  chipText: { color: '#E8E8F0', fontSize: 13 },
});
