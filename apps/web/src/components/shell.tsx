"use client";

import {
  BookOpen,
  FlaskConical,
  LayoutDashboard,
  MessagesSquare,
  Scale,
  Settings,
  Shapes,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

import { SignIn } from "./sign-in";

const links = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/strategies", label: "Strategies", icon: Shapes },
  { href: "/backtests", label: "Backtests", icon: FlaskConical },
  { href: "/assistant", label: "Assistant", icon: MessagesSquare },
  { href: "/arena", label: "Arena", icon: Scale },
  { href: "/learn", label: "Learn", icon: BookOpen },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [session, setSession] = useState<"loading" | "out" | "in">("loading");
  const [email, setEmail] = useState("");

  useEffect(() => {
    const token = sessionStorage.getItem("samar_token");
    if (!token) {
      setSession("out");
      return;
    }
    api<{ email: string }>("/auth/me")
      .then((me) => {
        setEmail(me.email);
        setSession("in");
      })
      .catch(() => {
        sessionStorage.removeItem("samar_token");
        setSession("out");
      });
  }, []);

  if (session === "loading") {
    return <div className="p-8 text-sm text-muted">Checking session</div>;
  }
  if (session === "out") {
    return (
      <SignIn
        onSuccess={(next) => {
          setEmail(next);
          setSession("in");
        }}
      />
    );
  }

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    sessionStorage.removeItem("samar_token");
    setSession("out");
  }

  return (
    <div className="min-h-screen">
      <p className="border-b border-line bg-surface px-4 py-2 text-center text-xs text-muted">
        Simulated. Not investment advice. Paper fills stay on Samar. A linked brokerage is read-only.
      </p>
      <div className="mx-auto flex max-w-page">
        <nav className="hidden w-52 shrink-0 border-r border-line p-4 md:block">
          <Link href="/" className="mb-6 block text-lg font-medium">
            Samar
          </Link>
          <ul className="space-y-1">
            {links.map((link) => {
              const active = path === link.href;
              const Icon = link.icon;
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className={`flex items-center gap-2 rounded-md px-2 py-2 text-sm ${
                      active ? "bg-surface text-ink" : "text-muted hover:text-ink"
                    }`}
                  >
                    <Icon size={16} />
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
          <button type="button" onClick={() => void logout()} className="mt-6 text-xs text-muted">
            Sign out {email}
          </button>
        </nav>
        <div className="min-w-0 flex-1">
          <div className="flex gap-2 overflow-x-auto border-b border-line p-3 md:hidden">
            {links.map((link) => (
              <Link key={link.href} href={link.href} className="text-sm text-muted">
                {link.label}
              </Link>
            ))}
          </div>
          <main className="p-4 md:p-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
