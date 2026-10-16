import * as React from 'react';

export interface BadgeProps {
  /** Severity/classification tier. `critical` is the only red tone. */
  tone?: 'critical' | 'high' | 'medium' | 'low' | 'neutral';
  /** Show a leading status dot in the tone color. */
  dot?: boolean;
  children?: React.ReactNode;
  style?: React.CSSProperties;
}

/**
 * Classification tier / status badge.
 * @startingPoint section="Status" subtitle="Severity tiers & status pills" viewport="700x100"
 */
export function Badge(props: BadgeProps): JSX.Element;
