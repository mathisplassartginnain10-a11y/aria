import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Markdown from 'react-native-markdown-display';

export type MessageRole = 'user' | 'assistant';

type Props = {
  role: MessageRole;
  text: string;
  streaming?: boolean;
};

export function MessageBubble({ role, text, streaming }: Props) {
  const isUser = role === 'user';

  return (
    <View style={[styles.row, isUser && styles.userRow]}>
      {!isUser && (
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>A</Text>
        </View>
      )}
      <View style={[styles.bubble, isUser ? styles.userBubble : styles.ariaBubble]}>
        {isUser ? (
          <Text style={styles.bubbleText}>{text}</Text>
        ) : (
          <Markdown style={markdownStyles}>
            {text + (streaming ? '▋' : '')}
          </Markdown>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, marginBottom: 4 },
  userRow: { flexDirection: 'row-reverse' },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 8,
    backgroundColor: 'rgba(108,142,255,0.1)',
    borderWidth: 1,
    borderColor: 'rgba(108,142,255,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { color: '#6C8EFF', fontWeight: '700', fontSize: 12 },
  bubble: { maxWidth: '80%', padding: 12, borderRadius: 16 },
  userBubble: {
    backgroundColor: '#17171E',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.06)',
    borderBottomRightRadius: 4,
  },
  ariaBubble: { borderBottomLeftRadius: 4 },
  bubbleText: { color: '#F1F1F3', fontSize: 15, lineHeight: 22 },
});

const markdownStyles = StyleSheet.create({
  body: { color: '#E8E8F0', fontSize: 15, lineHeight: 22 },
  code_inline: {
    backgroundColor: 'rgba(255,255,255,0.08)',
    color: '#6C8EFF',
    paddingHorizontal: 4,
    borderRadius: 4,
  },
  fence: {
    backgroundColor: '#17171E',
    color: '#E8E8F0',
    padding: 8,
    borderRadius: 8,
  },
});
