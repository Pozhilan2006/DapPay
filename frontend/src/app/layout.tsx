import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "DapPay | Payment Operations",
  description: "Read-only payment operations and reconciliation visibility.",
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
