import * as React from 'react';

export interface CaseCardProps {
  /** Monospace case identifier, e.g. "CASE-2026-0417". */
  caseId: string;
  title: string;
  tier?: 'critical' | 'high' | 'medium' | 'low' | 'neutral';
  /** Badge label; defaults to the tier name. */
  tierLabel?: string;
  actor?: string;
  updated?: string;
  openCount?: number;
  /** Highlighted/selected state. */
  active?: boolean;
  onClick?: () => void;
  style?: React.CSSProperties;
}

/**
 * Case summary card.
 * @startingPoint section="Console" subtitle="Case summary card" viewport="700x150"
 */
export function CaseCard(props: CaseCardProps): JSX.Element;
