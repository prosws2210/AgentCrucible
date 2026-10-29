// Small stroke icons (24px grid, currentColor).
type P = { className?: string };
const base = (d: React.ReactNode, className = "h-4 w-4") => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
    {d}
  </svg>
);

export const IconOverview = ({ className }: P) => base(<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>, className);
export const IconAgents = ({ className }: P) => base(<><rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 8V4.5M9.5 13h.01M14.5 13h.01M9.5 16h5" /><circle cx="12" cy="4" r="1" /></>, className);
export const IconGraph = ({ className }: P) => base(<><circle cx="5" cy="6" r="2.2" /><circle cx="19" cy="6" r="2.2" /><circle cx="12" cy="18" r="2.2" /><circle cx="12" cy="10" r="1.6" /><path d="M7 6.8l3.6 2.4M17 6.8l-3.6 2.4M12 11.6v4.2" /></>, className);
export const IconImport = ({ className }: P) => base(<><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5Z" /><path d="M12 11v5M9.5 13.5 12 16l2.5-2.5" /></>, className);
export const IconRuns = ({ className }: P) => base(<><path d="M5 4.5v15l13-7.5Z" /></>, className);
export const IconScenarios = ({ className }: P) => base(<><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></>, className);
export const IconServer = ({ className }: P) => base(<><rect x="3" y="4" width="18" height="7" rx="2" /><rect x="3" y="13" width="18" height="7" rx="2" /><path d="M7 7.5h.01M7 16.5h.01" /></>, className);
export const IconSetup = ({ className }: P) => base(<><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></>, className);
export const IconCheck = ({ className }: P) => base(<path d="M5 12.5 10 17.5 19 7" />, className);
export const IconX = ({ className }: P) => base(<path d="M6 6l12 12M18 6 6 18" />, className);
export const IconArrow = ({ className }: P) => base(<path d="M5 12h14M13 6l6 6-6 6" />, className);
export const IconExternal = ({ className }: P) => base(<><path d="M14 4h6v6" /><path d="M20 4 11 13" /><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" /></>, className);
export const IconPlus = ({ className }: P) => base(<path d="M12 5v14M5 12h14" />, className);
export const IconRefresh = ({ className }: P) => base(<><path d="M20 11a8 8 0 0 0-14.6-4.5L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16" /><path d="M20 20v-4h-4" /></>, className);
export const IconShield = ({ className }: P) => base(<path d="M12 3 5 6v5c0 4.5 3 8.5 7 10 4-1.5 7-5.5 7-10V6Z" />, className);
export const IconBolt = ({ className }: P) => base(<path d="M13 3 5 14h6l-1 7 8-11h-6Z" />, className);
export const IconCode = ({ className }: P) => base(<path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14" />, className);
export const IconChat = ({ className }: P) => base(<path d="M4 5h16v11H9l-5 4Z" />, className);
export const IconGit = ({ className }: P) => base(<><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="9" r="2.2" /><path d="M6 8.2v7.6M18 11.2c0 3-3 3.8-9.8 4.6" /></>, className);
export const IconBook = ({ className }: P) => base(<><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2Z" /><path d="M4 19V5" /></>, className);
export const IconMenu = ({ className }: P) => base(<path d="M4 7h16M4 12h16M4 17h16" />, className);
