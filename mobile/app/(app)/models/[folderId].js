import { useLocalSearchParams } from 'expo-router';
import ModelListScreen from '../../../src/screens/ModelListScreen';

export default function FolderScreen() {
  const { folderId } = useLocalSearchParams();
  return <ModelListScreen folderId={Number(folderId)} />;
}
