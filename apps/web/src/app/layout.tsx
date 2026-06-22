import type { Metadata } from "next";
import "./globals.css";
import { Inter } from "next/font/google";
import RouteWrapper from "@/components/RouteWrapper";

const inter = Inter({ subsets: ["latin", "cyrillic"] });

export const metadata: Metadata = {
  title: "Kamilya LMS",
  description: "AI-first корпоративная LMS для Казахстана",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body className={inter.className}>
        <RouteWrapper>{children}</RouteWrapper>
      </body>
    </html>
  );
}
