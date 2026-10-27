type IconProps = {
  size?: number;
  strokeWidth?: number;
  className?: string;
};

function base(size: number, strokeWidth: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

export function IconHome({ size = 18, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M4 11.5 12 4l8 7.5" />
      <path d="M6 10.5V20a1 1 0 0 0 1 1h3.5v-5.5h3V21H17a1 1 0 0 0 1-1v-9.5" />
    </svg>
  );
}

export function IconRadar({ size = 18, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <path d="M12 12l4-4" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" />
    </svg>
  );
}


export function IconUserAdd({ size = 18, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <circle cx="9" cy="7.5" r="3.5" />
      <path d="M2.5 20.5v-1a4.5 4.5 0 0 1 4.5-4.5h4a4.5 4.5 0 0 1 4.5 4.5v1" />
      <path d="M19 8v6M22 11h-6" />
    </svg>
  );
}

export function IconEditBig({ size = 18, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7.5 18.5 3 20l1.5-4.5z" />
    </svg>
  );
}

export function IconPopsicle({ size = 18, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M12 2.5c-3 0-5 2.2-5 5.2v6.6a5 5 0 0 0 10 0V7.7c0-3-2-5.2-5-5.2z" />
      <path d="M12 19.5v2" />
      <path d="M9.8 9.5h.01M14.2 9.5h.01" />
    </svg>
  );
}

export function IconChevronDownSmall({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M6 9.5l6 6 6-6" />
    </svg>
  );
}

export function IconCrossSmall({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

export function IconMagnifyingGlass({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

export function IconPlusMedium({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconCheckmarkSmall({ size = 18, strokeWidth = 2.4 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

export function IconSettingsGear({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

export function IconArrowBoxLeft({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M10 17l-5-5 5-5" />
      <path d="M5 12h9" />
      <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
    </svg>
  );
}

export function IconSidebarLeftArrow({
  size = 18,
  strokeWidth = 2,
  className,
}: IconProps) {
  return (
    <svg {...base(size, strokeWidth)} className={className}>
      <path d="M14 6l-6 6 6 6" />
      <path d="M20 4v16" />
    </svg>
  );
}

export function IconSun({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
    </svg>
  );
}

export function IconMoon({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}

export function IconDots({ size = 16, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="18" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="6" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconTrash({ size = 15, strokeWidth = 2 }: IconProps) {
  return (
    <svg {...base(size, strokeWidth)}>
      <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

