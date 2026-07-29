import VerificationPanel from '../VerificationPanel';

interface CertificateVerificationRouteProps {
  params: { number: string };
}

export default function CertificateVerificationRoute({ params }: CertificateVerificationRouteProps) {
  return <VerificationPanel initialNumber={decodeURIComponent(params.number)} />;
}
