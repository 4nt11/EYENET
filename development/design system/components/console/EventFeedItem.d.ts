import * as React from 'react';

export interface EventFeedItemProps {
  /** Monospace timestamp, e.g. "12:04:51". */
  time: string;
  /** Event kind — drives left-rail color. `alert` is the only red. */
  kind?: 'info' | 'observe' | 'alert' | 'system';
  /** Short uppercase label, e.g. "BEACON", "DNS". */
  label?: string;
  message: React.ReactNode;
  /** Monospace source/origin line under the message. */
  source?: string;
  /** Briefly highlight a just-arrived event. */
  fresh?: boolean;
  style?: React.CSSProperties;
}

/**
 * Streaming live-event feed row.
 * @startingPoint section="Console" subtitle="Streaming live-event feed row" viewport="700x120"
 */
export function EventFeedItem(props: EventFeedItemProps): JSX.Element;
