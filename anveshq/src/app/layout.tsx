import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Sidebar } from "@/components/layout/Sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Anveshq",
  description: "Momentum stock screener and paper trading engine.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${inter.className} bg-gray-50 text-gray-900 dark:bg-gray-900 dark:text-gray-50`}
      >
        <TooltipProvider>
          <div className="flex">
            <aside className="w-64 p-4">
              <Sidebar />
            </aside>
            <main className="flex-1 p-4">{children}</main>
          </div>
        </TooltipProvider>
      </body>
    </html>
  );
}
