import type { Metadata } from "next";
import "./globals.css";
import { Inter } from "next/font/google";
import RouteWrapper from "@/components/RouteWrapper";
import { Toaster } from "@/components/ui/Toast";
import { SkipToContent } from "@/components/a11y/SkipToContent";

const inter = Inter({ subsets: ["latin", "cyrillic"] });

export const metadata: Metadata = {
  title: "Kamilya LMS",
  description: "AI-first корпоративная LMS для Казахстана",
  icons: {
    icon: [
      {
        url:
          "data:image/svg+xml;utf8," +
          encodeURIComponent(
            `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
              <defs>
                <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#B8860B"/>
                  <stop offset="100%" stop-color="#2563EB"/>
                </linearGradient>
              </defs>
              <rect width="32" height="32" rx="6" fill="url(#g)"/>
              <text x="16" y="22" font-size="20" font-weight="700" fill="white" text-anchor="middle" font-family="sans-serif">K</text>
            </svg>`
          ),
        type: "image/svg+xml",
      },
    ],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body className={inter.className}>
        <SkipToContent />
        <RouteWrapper>
          {children}
          <Toaster />
        </RouteWrapper>
      </body>
    </html>
  );
}
