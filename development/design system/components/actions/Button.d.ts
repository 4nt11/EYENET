import * as React from 'react';

export interface ButtonProps {
  /** Visual role. Primary = purple, destructive = red, ghost/quiet for everything else. */
  variant?: 'primary' | 'destructive' | 'ghost' | 'quiet';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  /** Optional 14×14 icon node rendered before the label. */
  icon?: React.ReactNode;
  children?: React.ReactNode;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  type?: 'button' | 'submit' | 'reset';
  style?: React.CSSProperties;
}

/**
 * Console action button.
 * @startingPoint section="Actions" subtitle="Primary, destructive, ghost & quiet buttons" viewport="700x120"
 */
export function Button(props: ButtonProps): JSX.Element;
