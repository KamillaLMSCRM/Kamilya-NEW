import { ProductExample } from '@/features/product-example/ProductExample';
import { exampleCopy, resolveExampleLanguage } from '@/features/product-example/copy';

type ExamplePageProps = { searchParams: Promise<{ lang?: string | string[] }> };

export async function generateMetadata({ searchParams }: ExamplePageProps) {
  const params = await searchParams;
  return { title: `Kamilya LMS — ${exampleCopy[resolveExampleLanguage(params.lang)].title}` };
}

export default async function ExamplePage({ searchParams }: ExamplePageProps) {
  const params = await searchParams;
  return <ProductExample language={resolveExampleLanguage(params.lang)} />;
}
