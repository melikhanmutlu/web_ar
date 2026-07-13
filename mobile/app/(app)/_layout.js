import { Pressable, Text } from 'react-native';
import { Redirect, Stack } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';
import { BRAND } from '../../src/config';

function HeaderLogoutButton() {
  const { logout } = useAuth();
  return (
    <Pressable onPress={logout} hitSlop={12}>
      <Text style={{ color: '#fff', fontSize: 15 }}>Log Out</Text>
    </Pressable>
  );
}

export default function AppLayout() {
  const { token, isLoading } = useAuth();
  if (isLoading) return null;
  if (!token) return <Redirect href="/login" />;
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: BRAND.primary },
        headerTintColor: '#fff',
        headerTitleStyle: { fontWeight: '600' },
      }}
    >
      <Stack.Screen
        name="models/index"
        options={{ title: 'My Models', headerRight: () => <HeaderLogoutButton /> }}
      />
      <Stack.Screen name="models/[folderId]" options={{ title: 'Folder' }} />
      <Stack.Screen name="upload" options={{ title: 'Upload Model' }} />
      <Stack.Screen name="model/[modelId]" options={{ title: 'Model' }} />
    </Stack>
  );
}
