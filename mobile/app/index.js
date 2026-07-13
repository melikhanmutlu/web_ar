import { Redirect } from 'expo-router';

// (app)/_layout redirects on to /login if there's no token, so this just
// needs somewhere to send an unspecified "/" hit.
export default function Index() {
  return <Redirect href="/models" />;
}
