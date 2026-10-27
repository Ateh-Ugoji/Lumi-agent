import type React from 'react';
import styles from './LoadingDots.module.css';

type LoadingDotsProps = {
  label?: string;
  size?: number;
  gap?: number;
  className?: string;
};

const LoadingDots: React.FC<LoadingDotsProps> = ({
  label = 'Loading',
  size = 5,
  gap = 4,
  className,
}) => {
  return (
    <span
      className={className ? `${styles.dots} ${className}` : styles.dots}
      style={{ gap: `${gap}px` }}
      role="status"
      aria-label={label}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={styles.dot}
          style={{ width: `${size}px`, height: `${size}px` }}
        />
      ))}
    </span>
  );
};

export default LoadingDots;
