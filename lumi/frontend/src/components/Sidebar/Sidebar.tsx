import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useLightMode } from "../../hooks/useLightMode";
import GlideMenu from "./GlideMenu";
import {
  IconArrowBoxLeft,
  IconCheckmarkSmall,
  IconChevronDownSmall,
  IconCrossSmall,
  IconDots,
  IconEditBig,
  IconHome,
  IconMagnifyingGlass,
  IconMoon,
  IconPopsicle,
  IconRadar,
  IconSettingsGear,
  IconSidebarLeftArrow,
  IconSun,
  IconTrash,
  IconUserAdd,
} from "./Icons";
import styles from "./Sidebar.module.css";

const WORKSPACE = { key: "lumi", name: "Lumi", monogram: "L" };

const NAV_ITEMS: {
  key: string;
  label: string;
  icon: ReactNode;
  count?: string;
}[] = [
  { key: "home", label: "Home", icon: <IconHome size={18} /> },
  { key: "chronic", label: "Chronic Online", icon: <IconRadar size={18} /> },
  { key: "publish", label: "Publish", icon: <IconEditBig size={18} /> },
  { key: "settings", label: "Settings", icon: <IconSettingsGear size={18} /> },
];


export type SidebarRecent = {
  id: string;
  label: string;
  prompt?: string;
};

type SidebarNavProps = {
  activeTitle?: string | null;
  className?: string;
  fill?: boolean;
  onNewChat?: () => void;
  onPick?: (id: string, label: string, prompt?: string) => void;
  onDeleteChat?: (id: string) => void;
  activeNav?: string;
  onNavigate?: (key: string) => void;
  onOpenSettings?: (section: string) => void;
  footerLabel?: string;
  footerIcon?: ReactNode;
  onFooterClick?: () => void;
  onSignOut?: () => void;
  recents?: SidebarRecent[];
  userProfile?: { name: string; handle: string } | null;
};


const SIDEBAR_MOTION = {
  expandedWidth: 224,
  collapsedWidth: 52,
  duration: 280,
  copyDuration: 180,
  copyOffset: 8,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
};

const CHAT_SEARCH_MOTION = {
  duration: 180,
  closedWidth: 28,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
};

function GlideGroup({ children }: { children: ReactNode }) {
  return (
    <GlideMenu
      rowSelector="[data-row]"
      highlightClassName={styles.glideHighlight}
      className={styles.glideGroup}
    >
      {children}
    </GlideMenu>
  );
}

function RailButton({
  icon,
  label,
  active = false,
  count,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  count?: string;
  onClick?: () => void;
}) {
  return (
    <button
      data-row
      type="button"
      onClick={onClick}
      className={`${styles.railRow} ${active ? styles.railRowActive : ""}`}
    >
      <span
        className={`${styles.railIcon} ${active ? styles.inkText : ""}`}
      >
        {icon}
      </span>
      <span
        className={`${styles.copy} ${styles.railLabel} ${
          active ? styles.inkText : ""
        }`}
      >
        {label}
      </span>
      {count && (
        <span className={`${styles.copy} ${styles.railCount}`}>{count}</span>
      )}
    </button>
  );
}

function WorkspaceMenu({
  position,
  onClose,
  onOpenSettings,
  onSignOut,
}: {
  position: { top: number; left: number };
  onClose: () => void;
  onOpenSettings?: (section: string) => void;
  onSignOut?: () => void;
}) {
  const rows: { label: string; icon: ReactNode; section?: string }[] = [
    {
      label: "Profiles",
      icon: <IconSettingsGear size={16} />,
      section: "profile",
    },
    {
      label: "Connected accounts",
      icon: <IconUserAdd size={16} />,
      section: "social",
    },
  ];
  return createPortal(
    <div
      data-workspace-menu
      className={styles.workspaceMenu}
      style={{
        top: position.top,
        left: position.left,
        animation: "pop-in 180ms cubic-bezier(0.23,1,0.32,1) both",
        transformOrigin: "top left",
      }}
    >
      <GlideMenu
        rowSelector="[data-menu-row]"
        highlightClassName={styles.menuGlideHighlight}
        className={styles.menuGlideGroup}
      >
        <button
          data-menu-row
          type="button"
          onClick={onClose}
          className={`${styles.menuRow} ${styles.menuRowTall}`}
        >
          <span className={styles.monogram}>{WORKSPACE.monogram}</span>
          <span className={styles.menuLabel}>{WORKSPACE.name}</span>
          <span className={styles.menuCheck}>
            <IconCheckmarkSmall size={18} />
          </span>
        </button>
        <div className={styles.menuDivider} />
        {rows.map((item) => (
          <button
            key={item.label}
            data-menu-row
            type="button"
            onClick={() => {
              if (item.section) onOpenSettings?.(item.section);
              onClose();
            }}
            className={styles.menuRow}
          >
            <span className={styles.menuIcon}>{item.icon}</span>
            <span className={styles.menuLabel}>{item.label}</span>
          </button>
        ))}
        <div className={styles.menuDivider} />
        <button
          data-menu-row
          type="button"
          onClick={() => {
            onSignOut?.();
            onClose();
          }}
          className={styles.menuRow}
        >
          <span className={styles.menuIcon}>
            <IconArrowBoxLeft size={16} />
          </span>
          <span className={styles.menuLabel}>Sign out</span>
        </button>
      </GlideMenu>
    </div>,
    document.body,
  );
}

export default function SidebarNav({
  activeTitle,
  className = "",
  fill = false,
  onNewChat,
  onPick,
  onDeleteChat,
  activeNav,
  onNavigate,
  onOpenSettings,
  footerLabel = "New chat",
  footerIcon,
  onFooterClick,
  onSignOut,
  recents = [],
  userProfile = null,
}: SidebarNavProps) {
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== "undefined" && window.innerWidth < 900,
  );
  const narrowRef = useRef(
    typeof window !== "undefined" && window.innerWidth < 900,
  );
  const [internalNav, setInternalNav] = useState("chats");
  const currentNav = activeNav ?? internalNav;
  const selectNav = (key: string) => {
    setInternalNav(key);
    onNavigate?.(key);
  };
  const [demoActiveTitle, setDemoActiveTitle] = useState<string | null>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [workspacePosition, setWorkspacePosition] = useState({
    top: 0,
    left: 0,
  });
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [menuChatId, setMenuChatId] = useState<string | null>(null);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const workspaceButtonRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const { light, toggle: toggleTheme } = useLightMode();

  const selectedTitle =
    activeTitle === undefined ? demoActiveTitle : activeTitle;
  const visibleRecents = recents.filter((item) =>
    item.label.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const avatarHandle = userProfile?.handle ?? "";
  const avatarLetter = (userProfile?.name || userProfile?.handle || WORKSPACE.monogram)
    .trim()
    .charAt(0)
    .toUpperCase() || WORKSPACE.monogram;

  useEffect(() => {
    setAvatarFailed(false);
  }, [avatarHandle]);

  useEffect(() => {
    if (!menuChatId) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Element;
      if (!target.closest("[data-chat-menu]")) {
        setMenuChatId(null);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menuChatId]);

  useEffect(() => {
    if (!workspaceOpen) return;
    const close = (event: PointerEvent) => {

      const target = event.target as Element;
      if (
        !target.closest("[data-workspace-trigger]") &&
        !target.closest("[data-workspace-menu]")
      ) {
        setWorkspaceOpen(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [workspaceOpen]);

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  /* responsive: auto-collapse when the viewport crosses into narrow,
   * so the chat area never gets squeezed by an expanded rail */
  useEffect(() => {
    const onResize = () => {
      const narrow = window.innerWidth < 900;
      if (narrow && !narrowRef.current) {
        setCollapsed(true);
        setWorkspaceOpen(false);
        setSearchOpen(false);
        setQuery("");
      }
      narrowRef.current = narrow;
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const collapse = () => {
    setCollapsed(true);
    setWorkspaceOpen(false);
    setSearchOpen(false);
    setQuery("");
  };

  return (
    <aside
      data-sidebar-collapsed={collapsed}
      aria-label="Workspace navigation"
      className={`${styles.sidebar} ${fill ? styles.sidebarFill : styles.sidebarDemo} ${className}`}
      style={
        {
          width: collapsed
            ? SIDEBAR_MOTION.collapsedWidth
            : SIDEBAR_MOTION.expandedWidth,
          transitionDuration: `${SIDEBAR_MOTION.duration}ms`,
          transitionTimingFunction: SIDEBAR_MOTION.easing,
          "--sidebar-copy-duration": `${SIDEBAR_MOTION.copyDuration}ms`,
          "--sidebar-copy-offset": `${SIDEBAR_MOTION.copyOffset}px`,
          "--sidebar-easing": SIDEBAR_MOTION.easing,
        } as CSSProperties
      }
    >
      <div className={styles.inner}>
        <div className={styles.workspaceHeader}>
          <div
            data-avatar
            className={styles.userAvatar}
            aria-hidden={collapsed}
            title={userProfile ? `@${userProfile.handle}` : "View profile"}
          >
            {avatarHandle && !avatarFailed ? (
              <img
                className={styles.userAvatarImg}
                src={`https://unavatar.io/x/${avatarHandle}`}
                alt={userProfile?.name || avatarHandle}
                onError={() => setAvatarFailed(true)}
              />
            ) : (
              avatarLetter
            )}
          </div>
          <button
            ref={workspaceButtonRef}
            data-workspace-trigger
            type="button"
            aria-expanded={workspaceOpen}
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
            onClick={() => {
              if (!workspaceOpen && workspaceButtonRef.current) {
                const rect =
                  workspaceButtonRef.current.getBoundingClientRect();
                setWorkspacePosition({
                  top: rect.bottom + 6,
                  left: rect.left,
                });
              }
              setWorkspaceOpen((open) => !open);
            }}
            className={styles.workspaceControl}
          >
            <span className={styles.logo}>
              <IconPopsicle size={18} />
            </span>
            <span className={`${styles.copy} ${styles.workspaceName}`}>
              {userProfile ? `@${userProfile.handle}` : WORKSPACE.name}
            </span>
            <span className={`${styles.copy} ${styles.workspaceChev}`}>
              <IconChevronDownSmall size={16} />
            </span>
          </button>

          {workspaceOpen && (
            <WorkspaceMenu
              position={workspacePosition}
              onClose={() => setWorkspaceOpen(false)}
              onOpenSettings={onOpenSettings}
              onSignOut={onSignOut}
            />
          )}

          <button
            type="button"
            aria-label="Collapse sidebar"
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
            onClick={collapse}
            className={styles.collapseControl}
          >
            <IconSidebarLeftArrow size={18} />
          </button>
          <button
            type="button"
            aria-label="Expand sidebar"
            aria-hidden={!collapsed}
            tabIndex={collapsed ? 0 : -1}
            onClick={() => setCollapsed(false)}
            className={styles.expandControl}
          >
            <IconSidebarLeftArrow size={18} className={styles.rotate180} />
          </button>
        </div>

        <GlideGroup>
          <RailButton
            icon={<IconEditBig size={18} />}
            label="New chat"
            onClick={() => {
              if (activeTitle === undefined) setDemoActiveTitle(null);
              selectNav("chats");
              onNewChat?.();
            }}
          />
          {NAV_ITEMS.map((item) => (
            <RailButton
              key={item.key}
              icon={item.icon}
              label={item.label}
              count={item.count}
              active={currentNav === item.key}
              onClick={() => selectNav(item.key)}
            />
          ))}
        </GlideGroup>

        <div className={`${styles.copy} ${styles.history}`}>
          <div className={`${styles.copy} ${styles.chatsHeader}`}>
            <div
              aria-hidden={searchOpen}
              className={`${styles.chatsLabel} ${
                searchOpen ? styles.chatsLabelHidden : ""
              }`}
              style={{
                transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`,
                transitionTimingFunction: CHAT_SEARCH_MOTION.easing,
              }}
            >
              <IconChevronDownSmall size={16} />
              <span>Chats</span>
            </div>

            <button
              type="button"
              aria-label="Search chats"
              aria-expanded={searchOpen}
              onClick={() => setSearchOpen(true)}
              className={`${styles.searchBtn} ${
                searchOpen ? styles.searchBtnHidden : ""
              }`}
              style={{ transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms` }}
            >
              <IconMagnifyingGlass size={16} />
            </button>

            <div
              className={`${styles.searchField} ${
                searchOpen ? styles.searchFieldOpen : ""
              }`}
              style={{
                width: searchOpen
                  ? "100%"
                  : CHAT_SEARCH_MOTION.closedWidth,
                transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`,
                transitionTimingFunction: CHAT_SEARCH_MOTION.easing,
              }}
            >
              <span className={styles.searchIconBox}>
                <IconMagnifyingGlass size={15} />
              </span>
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setSearchOpen(false);
                    setQuery("");
                  }
                }}
                placeholder="Search chats"
                aria-label="Search chat history"
                className={styles.searchInput}
              />
              <button
                type="button"
                aria-label="Close chat search"
                onClick={() => {
                  setSearchOpen(false);
                  setQuery("");
                }}
                className={styles.searchClose}
              >
                <IconCrossSmall size={16} />
              </button>
            </div>
          </div>

          <GlideGroup>
            {visibleRecents.map((item) => {
              const active = item.label === selectedTitle;
              const isMenuOpen = menuChatId === item.id;
              return (
                <div
                  key={item.id}
                  data-row
                  data-chat-menu
                  className={`${styles.chatRowWrapper} ${
                    active ? styles.chatRowWrapperActive : ""
                  }`}
                >
                  <button
                    type="button"
                    title={item.label}
                    onClick={() => {
                      selectNav("chats");
                      if (activeTitle === undefined)
                        setDemoActiveTitle(item.label);
                      onPick?.(item.id, item.label, item.prompt);
                    }}
                    className={styles.chatRowLabelBtn}
                  >
                    <span
                      className={`${styles.copy} ${styles.railLabel} ${
                        active ? styles.inkText : ""
                      }`}
                    >
                      {item.label}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label="Chat options"
                    onClick={(e) => {
                      e.stopPropagation();
                      setMenuChatId(isMenuOpen ? null : item.id);
                    }}
                    className={`${styles.chatMenuBtn} ${
                      isMenuOpen ? styles.chatMenuBtnOpen : ""
                    }`}
                  >
                    <IconDots size={14} />
                  </button>
                  {isMenuOpen && (
                    <div className={styles.chatMenuDropdown}>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuChatId(null);
                          onDeleteChat?.(item.id);
                        }}
                        className={styles.chatMenuItemDelete}
                      >
                        <IconTrash size={14} />
                        <span>Delete chat</span>
                      </button>
                    </div>
                  )}
                </div>
              );
            })}

            {query && visibleRecents.length === 0 && (
              <div className={`${styles.copy} ${styles.noChats}`}>
                No chats found
              </div>
            )}
            {!query && recents.length === 0 && (
              <div className={`${styles.copy} ${styles.noChats}`}>
                No chats yet
              </div>
            )}
          </GlideGroup>
        </div>

        <GlideGroup>
          <RailButton
            icon={light ? <IconMoon size={18} /> : <IconSun size={18} />}
            label={light ? "Dark mode" : "Light mode"}
            onClick={toggleTheme}
          />
        </GlideGroup>

        <div className={`${styles.copy} ${styles.footer}`}>
          <button
            type="button"
            onClick={onFooterClick ?? onNewChat}
            className={styles.footerBtn}
          >
            {footerIcon}
            {footerLabel}
          </button>
        </div>
      </div>
    </aside>
  );
}
