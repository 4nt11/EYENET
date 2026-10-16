import * as React from 'react';

export interface EvidenceItem {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Values are monospace by default; set false for prose values. */
  mono?: boolean;
  /** Tint the value for emphasis. */
  tone?: 'default' | 'accent' | 'critical';
}

export interface EvidencePanelProps {
  title?: React.ReactNode;
  items: EvidenceItem[];
  /** Fixed label column width in px. Default 128. */
  labelWidth?: number;
  style?: React.CSSProperties;
}

/**
 * Key/value evidence panel.
 * @startingPoint section="Data" subtitle="Key/value evidence panel" viewport="700x240"
 */
export function EvidencePanel(props: EvidencePanelProps): JSX.Element;
