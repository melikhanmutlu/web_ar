import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, Image, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useAuth } from '../../../src/context/AuthContext';
import { getModel } from '../../../src/api/models';
import { launchModelInAR } from '../../../src/ar/launchAR';
import { BRAND } from '../../../src/config';

export default function ModelDetailScreen() {
  const { modelId } = useLocalSearchParams();
  const { token } = useAuth();
  const [model, setModel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [launching, setLaunching] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await getModel(token, modelId);
      setModel(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [token, modelId]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const onViewInAR = async () => {
    if (Platform.OS === 'ios' && !model.usdz_ready) {
      Alert.alert('AR not ready yet', 'This model’s AR version is still being generated. Try again in a moment.');
      return;
    }
    setLaunching(true);
    try {
      await launchModelInAR({ model, token });
    } catch (err) {
      Alert.alert('Could not launch AR', err.message);
    } finally {
      setLaunching(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={BRAND.accentDark} />
      </View>
    );
  }

  if (error || !model) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>{error || 'Model not found'}</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Image
        source={{ uri: model.thumbnail_url, headers: { Authorization: `Bearer ${token}` } }}
        style={styles.preview}
      />
      <Text style={styles.title}>{model.name}</Text>
      {model.description ? <Text style={styles.description}>{model.description}</Text> : null}

      <View style={styles.statsRow}>
        <Stat label="Format" value={(model.file_type || '').toUpperCase()} />
        <Stat label="Vertices" value={model.vertices ?? '—'} />
        <Stat label="Triangles" value={model.triangles ?? '—'} />
      </View>

      <Pressable
        style={[styles.arButton, launching && styles.arButtonDisabled]}
        onPress={onViewInAR}
        disabled={launching}
      >
        {launching ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.arButtonText}>View in AR</Text>
        )}
      </Pressable>
    </ScrollView>
  );
}

function Stat({ label, value }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  content: { padding: 20 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#fff' },
  error: { color: BRAND.danger, fontSize: 15, textAlign: 'center', paddingHorizontal: 24 },
  preview: {
    width: '100%', aspectRatio: 1, borderRadius: 12, backgroundColor: '#f3f4f6', marginBottom: 16,
  },
  title: { fontSize: 22, fontWeight: '700', color: BRAND.primary },
  description: { fontSize: 15, color: BRAND.muted, marginTop: 6 },
  statsRow: { flexDirection: 'row', marginTop: 20, marginBottom: 8 },
  stat: { flex: 1, alignItems: 'center' },
  statValue: { fontSize: 17, fontWeight: '600', color: BRAND.primary },
  statLabel: { fontSize: 12, color: BRAND.muted, marginTop: 2 },
  arButton: {
    backgroundColor: BRAND.accentDark, borderRadius: 10, padding: 16,
    alignItems: 'center', marginTop: 24,
  },
  arButtonDisabled: { opacity: 0.6 },
  arButtonText: { color: '#fff', fontWeight: '700', fontSize: 17 },
});
