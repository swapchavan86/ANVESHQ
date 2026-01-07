import type { Metadata } from "next";
import "./globals.css";
import { MainLayout } from "@/components/layout/MainLayout";

export const metadata: Metadata = {
  title: "Anveshq | Stock Market Intelligence",
  description: "Professional-grade stock analysis and risk assessment.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <MainLayout>{children}</MainLayout>
      </body>
    </html>
  );
}
