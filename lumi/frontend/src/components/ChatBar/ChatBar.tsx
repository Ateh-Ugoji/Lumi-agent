import clsx from "clsx";
import { useEffect, useRef } from "react";
import styles from "./ChatBar.module.css";

type ChatBarProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  placeholder?: string;
  maxLength?: number;
  busy?: boolean;
};

export default function ChatBar({
  value,
  onChange,
  onSend,
  placeholder = "Ask the agent…",
  maxLength = 2000,
  busy = false,
}: ChatBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const handleSend = () => {
    if (!value.trim() || busy) return;
    onSend();
  };

  return (
    <div className={styles.chatSticky}>
      <div className={styles.composerCard}>
        <div className={styles.inputBarWrapper} style={{ borderRadius: "20px" }}>
          <button
            type="button"
            className={styles.plusBtn}
            aria-label="Tools"
            disabled={busy}
          >
            <svg
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              width="20"
              height="20"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M12 4v16m8-8H4"
              />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            className={styles.composeInput}
            placeholder={placeholder}
            maxLength={maxLength}
            rows={1}
            value={value}
            style={{ borderRadius: "4px" }}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              flexDirection: "column",
              height: "100%",
              margin: "auto 0",
            }}
          >
            <span
              className={clsx(
                styles.charCounterInline,
                value.length >= maxLength * 0.9 &&
                  value.length < maxLength &&
                  styles.charWarn,
                value.length >= maxLength && styles.charLimit,
              )}
            >
              <span>{value.length}</span>/{maxLength}
            </span>
            {value.length > 5 && (
              <button
                type="button"
                className={styles.clearBtn}
                onClick={() => onChange("")}
              >
                <svg
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  width="16"
                  height="16"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            )}
          </div>
          <div className={styles.sendWrap}>
            <button
              type="button"
              className={styles.sendBtn}
              onClick={handleSend}
              disabled={!value.trim() || busy}
              aria-label="Send message"
            >
              {busy ? (
                <span className={styles.sendSpinner} />
              ) : (
                <svg
                  fill="currentColor"
                  viewBox="0 0 24 24"
                  width="20"
                  height="20"
                >
                  <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
