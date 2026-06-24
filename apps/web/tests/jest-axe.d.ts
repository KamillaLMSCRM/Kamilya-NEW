// Type shim for jest-axe (no @types/jest-axe package).
declare module 'jest-axe' {
  export const axe: (
    container: Element | string,
    options?: Record<string, unknown>
  ) => Promise<any>;
  export const toHaveNoViolations: any;
}
