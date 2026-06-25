'use client';

import React from 'react';

/**
 * Бренд-марка Kamilya: gold (#B8860B) → blue (#2563EB) градиент.
 * Используется в favicon (см. app/layout.tsx), sidebar, login/register/demo.
 *
 * Props:
 * - variant: 'mark' (только иконка) | 'full' (иконка + текст) | 'wordmark' (только текст)
 * - size: число пикселей для высоты иконки (default 32)
 * - withSubtitle: показывать "AI-платформа" под wordmark (только для sidebar)
 */
type LogoVariant = 'mark' | 'full' | 'wordmark';

interface LogoProps {
  variant?: LogoVariant;
  size?: number;
  withSubtitle?: boolean;
  className?: string;
  ariaLabel?: string;
}

export function Logo({
  variant = 'full',
  size = 32,
  withSubtitle = false,
  className = '',
  ariaLabel = 'Kamilya LMS',
}: LogoProps) {
  // SVG favicon design (gold→blue градиент + буква K)
  const mark = (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className="shrink-0"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="kamilya-gradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#B8860B" />
          <stop offset="100%" stopColor="#2563EB" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="6" fill="url(#kamilya-gradient)" />
      <text
        x="16"
        y="22"
        fontSize="20"
        fontWeight="700"
        fill="white"
        textAnchor="middle"
        fontFamily="Syne, system-ui, sans-serif"
      >
        K
      </text>
    </svg>
  );

  if (variant === 'mark') {
    return (
      <span className={className} aria-label={ariaLabel} role="img">
        {mark}
      </span>
    );
  }

  const wordmark = (
    <span
      className={`font-display font-bold tracking-tight ${
        variant === 'full' ? 'gradient-text' : 'text-primary'
      }`}
      style={{ fontSize: Math.max(16, size * 0.65), lineHeight: 1 }}
    >
      Kamilya
      <span className="text-foreground/60 font-normal"> LMS</span>
    </span>
  );

  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`} aria-label={ariaLabel}>
      {variant === 'full' && mark}
      <span className="flex flex-col">
        {wordmark}
        {withSubtitle && (
          <span
            className="text-xs text-muted-foreground font-medium tracking-wide uppercase mt-0.5"
            style={{ fontSize: Math.max(9, size * 0.32) }}
          >
            AI-платформа
          </span>
        )}
      </span>
    </span>
  );
}

export default Logo;