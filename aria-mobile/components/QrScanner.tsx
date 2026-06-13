import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';

type Props = {
  onScan: (data: string) => void;
  onClose: () => void;
};

export default function QrScanner({ onScan, onClose }: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);

  useEffect(() => {
    if (!permission?.granted) {
      requestPermission();
    }
  }, [permission, requestPermission]);

  if (!permission) {
    return (
      <View style={styles.overlay}>
        <Text style={styles.msg}>Accès caméra…</Text>
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.overlay}>
        <Text style={styles.msg}>Autorise la caméra pour scanner le QR du PC.</Text>
        <TouchableOpacity style={styles.btn} onPress={requestPermission}>
          <Text style={styles.btnText}>Autoriser</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={onClose}>
          <Text style={styles.link}>Annuler</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.overlay}>
      <CameraView
        style={styles.camera}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        onBarcodeScanned={({ data }) => {
          if (scanned) return;
          setScanned(true);
          onScan(data);
        }}
      />
      <View style={styles.frame} pointerEvents="none" />
      <Text style={styles.hint}>Scanne le QR affiché dans ARIA sur ton PC</Text>
      <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
        <Text style={styles.closeText}>✕</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#0C0C0F',
    zIndex: 100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  camera: { width: '100%', height: '100%' },
  frame: {
    position: 'absolute',
    width: 240,
    height: 240,
    borderWidth: 2,
    borderColor: '#6C8EFF',
    borderRadius: 16,
  },
  hint: {
    position: 'absolute',
    bottom: 80,
    color: '#F1F1F3',
    fontSize: 14,
    textAlign: 'center',
    paddingHorizontal: 32,
  },
  closeBtn: {
    position: 'absolute',
    top: 48,
    right: 24,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(0,0,0,0.5)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeText: { color: '#fff', fontSize: 18 },
  msg: { color: '#8B8B9E', fontSize: 14, textAlign: 'center', marginBottom: 16, paddingHorizontal: 32 },
  btn: {
    backgroundColor: '#6C8EFF',
    borderRadius: 12,
    paddingHorizontal: 24,
    paddingVertical: 12,
    marginBottom: 12,
  },
  btnText: { color: '#fff', fontWeight: '600' },
  link: { color: '#555', marginTop: 8 },
});
