// The Harvest-Call mark: a golden wheat ear between sound-wave arcs on deep green (same drawing as web/favicon.svg).
export default function Logo({ size = 34 }) {
  return (
    <svg className="logo" viewBox="0 0 512 512" width={size} height={size} aria-hidden="true" focusable="false">
      <rect width="512" height="512" rx="112" fill="#14231C" />
      <g fill="none" stroke="#F6F3EA" strokeWidth="18" strokeLinecap="round">
        <path d="M 344.3 203.0 A 112 112 0 0 1 344.3 341.0" />
        <path d="M 167.7 203.0 A 112 112 0 0 0 167.7 341.0" />
        <path d="M 383.7 172.3 A 162 162 0 0 1 383.7 371.7" />
        <path d="M 128.3 172.3 A 162 162 0 0 0 128.3 371.7" />
      </g>
      <path d="M 256 402 L 256 196" stroke="#E3A72F" strokeWidth="12" strokeLinecap="round" />
      <g fill="#E3A72F">
        {[224, 276, 328].map((y) => (
          <g key={y}>
            <ellipse cx="227" cy={y} rx="15" ry="33" transform={`rotate(-34 227 ${y})`} />
            <ellipse cx="285" cy={y} rx="15" ry="33" transform={`rotate(34 285 ${y})`} />
          </g>
        ))}
        <ellipse cx="256" cy="166" rx="15" ry="33" />
        <path d="M 256 392 Q 208 384 194 352 Q 234 352 256 392 Z" />
        <path d="M 256 392 Q 304 384 318 352 Q 278 352 256 392 Z" />
      </g>
    </svg>
  );
}
