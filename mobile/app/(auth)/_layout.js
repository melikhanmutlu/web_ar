import { Redirect, Stack } from 'expo-router';
import { useAuth } from '../../src/context/AuthContext';

export default function AuthLayout() {
  const { token, isLoading } = useAuth();
  if (isLoading) return null;
  if (token) return <Redirect href="/models" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
