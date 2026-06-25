'use client';

import { useEffect } from 'react';

export default function SkipLink() {
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-[9999] focus:bg-primary focus:text-primary-foreground focus:px-4 focus:py-2 focus:rounded focus:outline-none focus:ring-2 focus:ring-ring"
    >
      Skip to content
    </a>
  );
}
