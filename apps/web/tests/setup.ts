import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Mock next/link — return a function that creates elements without JSX in setup
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => ({
    type: 'a',
    props: { href, ...props, children, 'data-testid': 'next-link' },
  }),
}));

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
}));
