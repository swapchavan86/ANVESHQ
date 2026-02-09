"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, BarChart, Clock } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const links = [
  { href: "/dashboard", icon: Home, label: "Home" },
  { href: "/simulator", icon: BarChart, label: "Simulator" },
  { href: "/history", icon: Clock, label: "History" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col space-y-2">
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={cn(
            buttonVariants({ variant: "ghost" }),
            pathname === link.href
              ? "bg-muted hover:bg-muted"
              : "hover:bg-transparent hover:underline"
          )}
        >
          <link.icon className="mr-2 h-4 w-4" />
          {link.label}
        </Link>
      ))}
    </div>
  );
}
