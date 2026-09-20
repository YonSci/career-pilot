import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Career Pilot — Your personal job assistant",
  description: "Discover relevant opportunities, verify your experience, and prepare thoughtful applications.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
