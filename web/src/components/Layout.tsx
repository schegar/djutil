import { NavLink, Outlet, useNavigate } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { Disc3, History as HistoryIcon, Layers, LogOut, Radio } from "lucide-react";
import { api } from "../api/client";
import { cn } from "../lib/utils";

const TABS = [
  { to: "/live", label: "Live", icon: Radio },
  { to: "/", label: "Library", icon: Disc3 },
  { to: "/sets", label: "Sets", icon: Layers },
  { to: "/history", label: "History", icon: HistoryIcon },
];

export function Layout() {
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: () => api.logout(),
    onSettled: () => navigate("/login"),
  });

  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950">
      {/* Desktop top nav */}
      <header className="sticky top-0 z-30 hidden border-b border-neutral-800 bg-neutral-950/90 backdrop-blur md:block">
        <div className="mx-auto flex h-12 max-w-7xl items-center gap-6 px-4">
          <span className="font-bold tracking-tight">DJUtil</span>
          <nav className="flex gap-1">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-sm",
                    isActive
                      ? "bg-neutral-800 text-neutral-100"
                      : "text-neutral-400 hover:text-neutral-100",
                  )
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
          <button
            onClick={() => logout.mutate()}
            className="ml-auto flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-neutral-400 hover:text-neutral-100"
          >
            <LogOut className="h-4 w-4" /> Logout
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-2 pb-20 pt-3 md:px-4 md:pb-4">
        <Outlet />
      </main>

      {/* Mobile bottom tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-neutral-800 bg-neutral-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex flex-1 flex-col items-center gap-0.5 py-2 text-xs",
                isActive ? "text-neutral-100" : "text-neutral-500",
              )
            }
          >
            <t.icon className="h-5 w-5" />
            {t.label}
          </NavLink>
        ))}
        <button
          onClick={() => logout.mutate()}
          className="flex flex-1 flex-col items-center gap-0.5 py-2 text-xs text-neutral-500"
        >
          <LogOut className="h-5 w-5" />
          Logout
        </button>
      </nav>
    </div>
  );
}
