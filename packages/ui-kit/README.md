# UI Kit

```json
{
  "name": "ui-kit",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "index.ts",
  "types": "index.ts",
  "exports": {
    ".": "./index.ts",
    "./button": "./components/button.tsx",
    "./card": "./components/card.tsx",
    "./input": "./components/input.tsx",
    "./modal": "./components/modal.tsx",
    "./badge": "./components/badge.tsx",
    "./table": "./components/table.tsx"
  },
  "peerDependencies": {
    "react": "^18.3",
    "react-dom": "^18.3"
  },
  "dependencies": {
    "tailwind-merge": "^2.6",
    "class-variance-authority": "^0.7"
  },
  "devDependencies": {
    "@types/react": "^18.3",
    "typescript": "^5.6"
  }
}
```

## Компоненты

| Компонент | Описание |
|-----------|----------|
| `Button` | Кнопки с variant (default, destructive, outline, ghost) и size |
| `Card` | Карточка с CardHeader, CardTitle, CardContent |
| `Input` | Стандартный input с Tailwind стилями Kamilya |
| `Modal` | Модальное окно с title и children |
| `Badge` | Бейдж с variant (default, secondary, destructive, outline) |
| `Table` | Таблица с columns и data |

Все компоненты используют `cn()` из `@/lib/utils` для className merge.
