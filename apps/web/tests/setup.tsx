import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Mock next/link since it's not available in jsdom
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) =>
    <a href={href} {...props} data-testid="next-link">{children}</a>,
}));

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));
