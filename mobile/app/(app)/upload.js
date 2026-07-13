import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { File } from 'expo-file-system';
import { useRouter } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';
import { isAllowedModelFile, pollJobStatus, uploadModelFile } from '../../src/api/upload';
import { BRAND } from '../../src/config';

const ALLOWED_LABEL = 'STL, FBX, OBJ, STEP, GLB, or glTF';

export default function UploadScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const [file, setFile] = useState(null);
  const [stage, setStage] = useState('idle'); // idle | uploading | converting | error
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState('');
  const [error, setError] = useState(null);

  const onPickFile = async () => {
    setError(null);
    const result = await File.pickFileAsync({ mimeTypes: '*/*' });
    if (result.canceled) return;
    const picked = result.result;
    if (!isAllowedModelFile(picked)) {
      setError(`Unsupported file type. Allowed: ${ALLOWED_LABEL}`);
      return;
    }
    setFile(picked);
  };

  const onUpload = async () => {
    if (!file) return;
    setError(null);
    setStage('uploading');
    setProgress(0);
    try {
      const complete = await uploadModelFile(token, file, { onProgress: setProgress });
      setStage('converting');
      setStatusText('Converting…');
      const finalStatus = await pollJobStatus(complete.job_id, complete.status_token, {
        onUpdate: (status) => setStatusText(status.stage || status.status),
      });
      if (finalStatus.status !== 'completed' || !finalStatus.model_id) {
        throw new Error(finalStatus.error || 'Conversion failed');
      }
      router.replace(`/model/${finalStatus.model_id}`);
    } catch (err) {
      setStage('error');
      setError(err.message);
    }
  };

  const busy = stage === 'uploading' || stage === 'converting';

  return (
    <View style={styles.container}>
      <Pressable style={styles.pickButton} onPress={onPickFile} disabled={busy}>
        <Text style={styles.pickButtonText}>{file ? file.name : 'Choose a 3D model file'}</Text>
      </Pressable>
      <Text style={styles.hint}>Supported formats: {ALLOWED_LABEL}</Text>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {stage === 'uploading' ? (
        <View style={styles.progressBlock}>
          <ActivityIndicator color={BRAND.accentDark} />
          <Text style={styles.progressText}>Uploading… {Math.round(progress * 100)}%</Text>
        </View>
      ) : null}

      {stage === 'converting' ? (
        <View style={styles.progressBlock}>
          <ActivityIndicator color={BRAND.accentDark} />
          <Text style={styles.progressText}>{statusText}</Text>
        </View>
      ) : null}

      <Pressable
        style={[styles.uploadButton, (!file || busy) && styles.uploadButtonDisabled]}
        onPress={onUpload}
        disabled={!file || busy}
      >
        <Text style={styles.uploadButtonText}>Upload</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff', padding: 24 },
  pickButton: {
    borderWidth: 2, borderColor: BRAND.border, borderStyle: 'dashed', borderRadius: 12,
    padding: 24, alignItems: 'center', marginTop: 12,
  },
  pickButtonText: { fontSize: 16, color: BRAND.primary, textAlign: 'center' },
  hint: { color: BRAND.muted, fontSize: 13, textAlign: 'center', marginTop: 10 },
  error: { color: BRAND.danger, marginTop: 16, textAlign: 'center' },
  progressBlock: { alignItems: 'center', marginTop: 24 },
  progressText: { marginTop: 10, color: BRAND.primary, fontSize: 15 },
  uploadButton: {
    backgroundColor: BRAND.accentDark, borderRadius: 10, padding: 16,
    alignItems: 'center', marginTop: 32,
  },
  uploadButtonDisabled: { opacity: 0.5 },
  uploadButtonText: { color: '#fff', fontWeight: '700', fontSize: 17 },
});
