import clsx from "clsx";
import styles from "./AmbientBackground.module.css";

export default function AmbientBackground() {
  return (
    <div className={styles.ambientBg}>
      <div className={clsx(styles.orb, styles.orb1)} />
      <div className={clsx(styles.orb, styles.orb2)} />
      <div className={clsx(styles.orb, styles.orb3)} />
      <div className={clsx(styles.orb, styles.orb4)} />
      <div className={clsx(styles.orb, styles.orb5)} />
    </div>
  );
}
