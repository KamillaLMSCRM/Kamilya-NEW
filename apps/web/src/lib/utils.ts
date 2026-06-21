import React from 'react';

export function cn(...classes: (string | null | undefined | false)[]) {
  return classes.filter(Boolean).join(' ');
}
