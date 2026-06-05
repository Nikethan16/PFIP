import type { Config } from "tailwindcss";

// Tremor preset — we re-declare the bits Tremor needs so we don't depend on
// a separately installed preset file. Keeps `tailwind.config.ts` self-contained.
const tremorConfig = {
  transparent: "transparent",
  current: "currentColor",
  tremor: {
    brand: {
      faint: "#eff6ff",
      muted: "#bfdbfe",
      subtle: "#60a5fa",
      DEFAULT: "#3b82f6",
      emphasis: "#1d4ed8",
      inverted: "#ffffff",
    },
    background: {
      muted: "#f9fafb",
      subtle: "#f3f4f6",
      DEFAULT: "#ffffff",
      emphasis: "#374151",
    },
    border: { DEFAULT: "#e5e7eb" },
    ring: { DEFAULT: "#e5e7eb" },
    content: {
      subtle: "#9ca3af",
      DEFAULT: "#6b7280",
      emphasis: "#374151",
      strong: "#111827",
      inverted: "#ffffff",
    },
  },
  "dark-tremor": {
    brand: {
      faint: "#0B1229",
      muted: "#172554",
      subtle: "#1e40af",
      DEFAULT: "#3b82f6",
      emphasis: "#60a5fa",
      inverted: "#030712",
    },
    background: {
      muted: "#131A2B",
      subtle: "#1f2937",
      DEFAULT: "#111827",
      emphasis: "#d1d5db",
    },
    border: { DEFAULT: "#1f2937" },
    ring: { DEFAULT: "#1f2937" },
    content: {
      subtle: "#4b5563",
      DEFAULT: "#6b7280",
      emphasis: "#e5e7eb",
      strong: "#f9fafb",
      inverted: "#000000",
    },
  },
};

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    // Tremor dist — needed for class extraction
    "./node_modules/@tremor/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    transparent: "transparent",
    current: "currentColor",
    extend: {
      colors: {
        // shadcn/ui
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Tremor palette
        ...tremorConfig,
        // -----------------------------------------------------------------
        // Slate & Teal Institutional tokens — ported from Google Stitch.
        // These keep the Stitch HTML classes (`bg-surface`, `text-positive`,
        // etc.) working verbatim when we drop their markup into React.
        // The shadcn tokens above remain the source of truth for theming.
        // -----------------------------------------------------------------
        surface: "#f8f9ff",
        "surface-dim": "#cbdbf5",
        "surface-bright": "#f8f9ff",
        "surface-container-lowest": "#ffffff",
        "surface-container-low": "#eff4ff",
        "surface-container": "#e5eeff",
        "surface-container-high": "#dce9ff",
        "surface-container-highest": "#d3e4fe",
        "on-surface": "#0b1c30",
        "on-surface-variant": "#3c4947",
        "inverse-surface": "#213145",
        "inverse-on-surface": "#eaf1ff",
        outline: "#6c7a77",
        "outline-variant": "#bbcac6",
        "primary-container": "#14b8a6",
        "on-primary-container": "#00423b",
        "inverse-primary": "#4fdbc8",
        "secondary-container": "#dae2fd",
        "on-secondary-container": "#5c647a",
        positive: "#10b981",
        negative: "#ef4444",
        // Status palette (kept semantic so dashboards stay consistent).
        signal: {
          buy: "#10b981",
          sell: "#ef4444",
          hold: "#f59e0b",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      width: {
        "sidebar-width": "220px",
      },
      spacing: {
        gutter: "16px",
        "component-gap": "12px",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        "tremor-small": "0.375rem",
        "tremor-default": "0.5rem",
        "tremor-full": "9999px",
      },
      fontSize: {
        "tremor-label": ["0.75rem", { lineHeight: "1rem" }],
        "tremor-default": ["0.875rem", { lineHeight: "1.25rem" }],
        "tremor-title": ["1.125rem", { lineHeight: "1.75rem" }],
        "tremor-metric": ["1.875rem", { lineHeight: "2.25rem" }],
        // Stitch scale.
        "headline-lg": ["32px", { lineHeight: "40px", letterSpacing: "-0.02em", fontWeight: "600" }],
        "headline-md": ["24px", { lineHeight: "32px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "headline-sm": ["18px", { lineHeight: "24px", fontWeight: "600" }],
        "body-lg": ["16px", { lineHeight: "24px", fontWeight: "400" }],
        "body-md": ["14px", { lineHeight: "20px", fontWeight: "400" }],
        "body-sm": ["13px", { lineHeight: "18px", fontWeight: "400" }],
        "label-md": ["12px", { lineHeight: "16px", fontWeight: "500" }],
        "label-sm": ["10px", { lineHeight: "14px", letterSpacing: "0.02em", fontWeight: "500" }],
        "numeric-lg": ["24px", { lineHeight: "32px", fontWeight: "600" }],
        "numeric-md": ["16px", { lineHeight: "24px", fontWeight: "500" }],
        "numeric-sm": ["12px", { lineHeight: "16px", fontWeight: "500" }],
      },
      boxShadow: {
        "tremor-input": "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        "tremor-card":
          "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        "tremor-dropdown":
          "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  safelist: [
    // Tremor emits color/size classes dynamically; safelist the common ones.
    {
      pattern:
        /^(bg-|text-|border-|ring-|fill-|stroke-)(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(50|100|200|300|400|500|600|700|800|900|950)$/,
      variants: ["hover", "ui-selected"],
    },
  ],
  plugins: [require("tailwindcss-animate")],
};

export default config;
