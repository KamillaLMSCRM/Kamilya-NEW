import VerificationPanel from '../VerificationPanel';

interface CertificateVerificationRouteProps {
  params: Promise<{ number: string }>;
}

export default async function CertificateVerificationRoute({ params }: CertificateVerificationRouteProps) {
  const { number } = await params;
  return <VerificationPanel initialNumber={decodeURIComponent(number)} />;
}
