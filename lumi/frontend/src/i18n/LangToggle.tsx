import { LANGS, setLang, useLang } from "./index";
import styles from "./LangToggle.module.css";

/** The EN | ES switch shown in Settings and on the login page. */
export default function LangToggle({ className = "" }: { className?: string }) {
  const lang = useLang();
  return (
    <div
      className={`${styles.group} ${className}`}
      role="group"
      aria-label="Language / Idioma"
    >
      {LANGS.map((code) => (
        <button
          key={code}
          type="button"
          aria-pressed={lang === code}
          className={lang === code ? styles.active : styles.btn}
          onClick={() => setLang(code)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
