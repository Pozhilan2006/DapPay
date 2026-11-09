import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "PayRecon AI",
  description: "Financial intelligence for PayPal reconciliation workflows.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
