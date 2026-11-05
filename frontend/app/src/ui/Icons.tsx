// Small drawn glyphs (no emoji: they render differently on every OS and read as decoration).
type P = { size?: number; className?: string };

export const SunIcon = ({ size = 14, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <circle cx="8" cy="8" r="3.2" fill="currentColor" />
    {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
      <line key={a} x1="8" y1="1.2" x2="8" y2="3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" transform={`rotate(${a} 8 8)`} />
    ))}
  </svg>
);

export const EarthIcon = ({ size = 14, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
    <path d="M8 2c-2.2 2-2.2 10 0 12M8 2c2.2 2 2.2 10 0 12M2.3 6h11.4M2.3 10h11.4" fill="none" stroke="currentColor" strokeWidth="1" />
  </svg>
);

export const ClockIcon = ({ size = 14, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
    <path d="M8 4.5V8l2.5 1.6" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export const CalIcon = ({ size = 14, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <rect x="2" y="3" width="12" height="11" fill="none" stroke="currentColor" strokeWidth="1.3" />
    <path d="M2 6.5h12M5 1.5v3M11 1.5v3" stroke="currentColor" strokeWidth="1.3" />
    <rect x="9" y="9" width="3" height="3" fill="currentColor" />
  </svg>
);

export const CloseIcon = ({ size = 14, className }: P) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className={className}>
    <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

export const PlayIcon = ({ playing, size = 12 }: { playing: boolean; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
    {playing ? <path d="M6 4h4v16H6zM14 4h4v16h-4z" /> : <path d="M7 4l13 8-13 8z" />}
  </svg>
);

export const Mark = () => (
  <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
    <circle cx="11" cy="11" r="9.5" fill="#11151c" stroke="#3a414c" />
    <path d="M11 1.5A9.5 9.5 0 0 1 11 20.5 5.2 9.5 0 0 1 11 1.5Z" fill="#d6d2c9" />
    <path d="M1 11h20M11 1v20" stroke="#04060a" strokeWidth="0.8" opacity="0.5" />
  </svg>
);
