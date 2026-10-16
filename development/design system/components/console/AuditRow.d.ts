import * as React from 'react';

export interface AuditRowProps {
  /** Monospace UTC timestamp. */
  time: string;
  /** Actor / operator id (monospace). */
  actor: string;
  /** Action verb, e.g. "reclassified", "sealed". */
  verb?: string;
  /** Monospace target of the action. */
  target?: string;
  /** Trailing prose detail. */
  detail?: string;
  /** Flags an integrity/tamper event — turns the row red. */
  tamper?: boolean;
  /** Free-form action content, overrides verb/target/detail. */
  children?: React.ReactNode;
  style?: React.CSSProperties;
}

/**
 * Immutable audit-trail row.
 * @startingPoint section="Console" subtitle="Immutable audit-trail row" viewport="700x110"
 */
export function AuditRow(props: AuditRowProps): JSX.Element;
