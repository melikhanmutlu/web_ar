import { useCallback, useState } from 'react';
import { ActivityIndicator, FlatList, Image, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { Link, useFocusEffect, useRouter } from 'expo-router';
import { useAuth } from '../context/AuthContext';
import { listFolders, listModels } from '../api/models';
import { BRAND } from '../config';

// The thumbnail endpoint (GET /api/v1/models/<id>/thumbnail) is Bearer-token
// gated like every other mobile API route and 404s when no thumbnail has
// been cached yet -- this renders a placeholder in both cases rather than a
// broken-image icon.
function ModelThumbnail({ url, token }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return (
      <View style={[styles.thumbnail, styles.thumbnailPlaceholder]}>
        <Text style={styles.thumbnailPlaceholderText}>📦</Text>
      </View>
    );
  }
  return (
    <Image
      source={{ uri: url, headers: { Authorization: `Bearer ${token}` } }}
      style={styles.thumbnail}
      onError={() => setFailed(true)}
    />
  );
}

// folderId: undefined/null means the root level. Reused by both
// app/(app)/models/index.js and app/(app)/models/[folderId].js.
export default function ModelListScreen({ folderId }) {
  const { token } = useAuth();
  const router = useRouter();
  const [folders, setFolders] = useState([]);
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [foldersRes, modelsRes] = await Promise.all([
        listFolders(token, folderId),
        listModels(token, folderId ?? null),
      ]);
      setFolders(foldersRes.data);
      setModels(modelsRes.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, folderId]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  const items = [
    ...folders.map((f) => ({ type: 'folder', key: `folder-${f.id}`, data: f })),
    ...models.map((m) => ({ type: 'model', key: `model-${m.id}`, data: m })),
  ];

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={BRAND.accentDark} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <FlatList
        data={items}
        keyExtractor={(item) => item.key}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={items.length === 0 && styles.emptyContainer}
        ListEmptyComponent={
          <Text style={styles.emptyText}>No folders or models here yet.</Text>
        }
        renderItem={({ item }) =>
          item.type === 'folder' ? (
            <Pressable
              style={styles.row}
              onPress={() => router.push(`/models/${item.data.id}`)}
            >
              <Text style={styles.rowIcon}>📁</Text>
              <View style={styles.rowText}>
                <Text style={styles.rowTitle}>{item.data.name}</Text>
                <Text style={styles.rowSubtitle}>
                  {item.data.model_count} {item.data.model_count === 1 ? 'model' : 'models'}
                </Text>
              </View>
            </Pressable>
          ) : (
            <Pressable style={styles.row} onPress={() => router.push(`/model/${item.data.id}`)}>
              <ModelThumbnail url={item.data.thumbnail_url} token={token} />
              <View style={styles.rowText}>
                <Text style={styles.rowTitle}>{item.data.name}</Text>
                <Text style={styles.rowSubtitle}>{(item.data.file_type || '').toUpperCase()}</Text>
              </View>
            </Pressable>
          )
        }
      />
      <Link href="/upload" asChild>
        <Pressable style={styles.fab}>
          <Text style={styles.fabText}>+</Text>
        </Pressable>
      </Link>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#fff' },
  error: { color: BRAND.danger, padding: 12, textAlign: 'center' },
  emptyContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  emptyText: { color: BRAND.muted, fontSize: 15 },
  row: {
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: BRAND.border,
  },
  rowIcon: { fontSize: 28, width: 44, textAlign: 'center' },
  thumbnail: { width: 44, height: 44, borderRadius: 6, backgroundColor: '#f3f4f6' },
  thumbnailPlaceholder: { justifyContent: 'center', alignItems: 'center' },
  thumbnailPlaceholderText: { fontSize: 20 },
  rowText: { marginLeft: 12, flex: 1 },
  rowTitle: { fontSize: 16, fontWeight: '500', color: BRAND.primary },
  rowSubtitle: { fontSize: 13, color: BRAND.muted, marginTop: 2 },
  fab: {
    position: 'absolute', right: 20, bottom: 20, width: 56, height: 56, borderRadius: 28,
    backgroundColor: BRAND.accentDark, justifyContent: 'center', alignItems: 'center',
    elevation: 4, shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 4, shadowOffset: { width: 0, height: 2 },
  },
  fabText: { color: '#fff', fontSize: 28, lineHeight: 30 },
});
