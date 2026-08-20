export type ScormBridgeStatus = 'loading' | 'ready' | 'saving' | 'saved' | 'completed' | 'error';

interface TrustedScormBridgeExpectation {
  origin: string;
  channel: string;
  source: MessageEventSource | null;
}

const SCORM_BRIDGE_STATUSES = new Set<ScormBridgeStatus>([
  'loading',
  'ready',
  'saving',
  'saved',
  'completed',
  'error',
]);

export function isTrustedScormBridgeMessage(
  event: Pick<MessageEvent, 'origin' | 'source' | 'data'>,
  expected: TrustedScormBridgeExpectation,
): event is MessageEvent<{
  version: 1;
  type: 'kamilya.scorm.status';
  channel: string;
  status: ScormBridgeStatus;
}> {
  if (event.origin !== expected.origin || event.source !== expected.source) return false;
  if (!event.data || typeof event.data !== 'object' || Array.isArray(event.data)) return false;
  const data = event.data as Record<string, unknown>;
  return data.version === 1
    && data.type === 'kamilya.scorm.status'
    && data.channel === expected.channel
    && typeof data.status === 'string'
    && SCORM_BRIDGE_STATUSES.has(data.status as ScormBridgeStatus);
}
