"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Boxes,
  ArrowRightLeft,
  Route,
  Layers,
  History,
  PackageCheck,
  Truck,
  FilePlus,
  FileSpreadsheet,
  AlertTriangle,
  FileText,
  Bot,
  ShieldAlert,
  Sun,
  Moon,
  Menu,
  X,
  LogOut,
  Bell,
  Search,
  ChevronRight,
  Factory,
  Sparkles,
  CheckSquare,
  Shuffle
} from "lucide-react";
import { logout, getCurrentUserRole } from "@/lib/api";

// STORE is a physical material-handling role: it must see only the navigation it is
// actually authorized to use (Move Parts, and Rejection Tracking for melting-entry
// execution), never the planning/quality/dispatch/admin surfaces those roles govern.
// Every other existing role's navigation is left exactly as it was -- this allowlist
// only ever narrows what STORE specifically sees.
const STORE_ALLOWED_HREFS = new Set([
  "/dashboard",
  "/production/move",
  "/production/tracking",
  "/production/history",
  "/quality/nc",
]);

interface NavItem {
  name: string;
  href: string;
  icon: React.ReactNode;
  badge?: string;
  roles?: string[];
}

interface NavGroup {
  group: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    group: "OVERVIEW",
    items: [
      {
        name: "Dashboard",
        href: "/dashboard",
        icon: <LayoutDashboard className="h-4 w-4" />,
      },
      {
        name: "AI Copilot",
        href: "/ai",
        icon: <Bot className="h-4 w-4 text-purple-500" />,
        badge: "AI Live",
      },
    ],
  },
  {
    group: "PRODUCTION & WIP",
    items: [
      {
        name: "Production Entry",
        href: "/production/entry",
        icon: <CheckSquare className="h-4 w-4 text-emerald-500" />,
        badge: "Entry",
      },
      {
        name: "Move Parts (Shop Floor)",
        href: "/production/move",
        icon: <ArrowRightLeft className="h-4 w-4 text-blue-500" />,
        badge: "Floor",
      },
      {
        name: "WO Tracking & Timeline",
        href: "/production/tracking",
        icon: <Route className="h-4 w-4 text-purple-500" />,
      },
      {
        name: "Live WIP Matrix",
        href: "/production/wip",
        icon: <Layers className="h-4 w-4 text-amber-500" />,
      },
      {
        name: "Movement History",
        href: "/production/history",
        icon: <History className="h-4 w-4" />,
      },
    ],
  },
  {
    group: "PACKING & DISPATCH",
    items: [
      {
        name: "Packing / BSR Queue",
        href: "/packing",
        icon: <PackageCheck className="h-4 w-4 text-cyan-500" />,
      },
      {
        name: "Dispatch Center",
        href: "/dispatch",
        icon: <Truck className="h-4 w-4 text-emerald-500" />,
      },
    ],
  },
  {
    group: "OPERATIONS & PLANNING",
    items: [
      {
        name: "Order Intake (OAR)",
        href: "/orders/intake",
        icon: <FilePlus className="h-4 w-4" />,
      },
      {
        name: "OAR & WO List",
        href: "/orders/list",
        icon: <FileSpreadsheet className="h-4 w-4 text-blue-500" />,
      },
      {
        name: "WO Release & Routing",
        href: "/planning/wo-release",
        icon: <Factory className="h-4 w-4" />,
      },
      {
        name: "Conversion Module",
        href: "/planning/conversion",
        icon: <ArrowRightLeft className="h-4 w-4 text-indigo-500" />,
      },
      {
        name: "Conversion Part Mapping",
        href: "/planning/conversion-mapping",
        icon: <Shuffle className="h-4 w-4 text-indigo-500" />,
      },
      {
        name: "Rejection Tracking",
        href: "/quality/nc",
        icon: <AlertTriangle className="h-4 w-4 text-rose-500" />,
      },
    ],
  },
  {
    group: "INTELLIGENCE & REPORTS",
    items: [
      {
        name: "OMS Engine Batch",
        href: "/oms",
        icon: <FileSpreadsheet className="h-4 w-4 text-emerald-600" />,
      },
      {
        name: "Manufacturing Reports",
        href: "/reports",
        icon: <FileText className="h-4 w-4" />,
      },
    ],
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [userRole, setUserRole] = useState<string | null>(null);
  const [notificationCount, setNotificationCount] = useState(3);
  const [showNotifications, setShowNotifications] = useState(false);

  useEffect(() => {
    setUserRole(getCurrentUserRole());
  }, []);

  const visibleNavGroups = userRole === "store"
    ? NAV_GROUPS
        .map((grp) => ({ ...grp, items: grp.items.filter((item) => STORE_ALLOWED_HREFS.has(item.href)) }))
        .filter((grp) => grp.items.length > 0)
    : NAV_GROUPS;

  useEffect(() => {
    // Detect system dark mode or stored preference
    if (localStorage.getItem("theme") === "dark" || (!("theme" in localStorage) && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
      setDarkMode(true);
      document.documentElement.classList.add("dark");
    } else {
      setDarkMode(false);
      document.documentElement.classList.remove("dark");
    }
  }, []);

  const toggleDarkMode = () => {
    if (darkMode) {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
      setDarkMode(false);
    } else {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
      setDarkMode(true);
    }
  };

  return (
    <div className="flex min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 font-sans antialiased">
      {/* Mobile backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-zinc-200 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/95 backdrop-blur transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Brand Header */}
        <div className="flex h-16 items-center justify-between border-b border-zinc-200 dark:border-zinc-800 px-6">
          <Link href="/dashboard" className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-indigo-700 text-white shadow-md shadow-blue-500/20 font-bold text-lg">
              V
            </div>
            <div>
              <span className="font-bold text-base tracking-tight text-zinc-900 dark:text-zinc-100">
                VSPL <span className="text-blue-600 dark:text-blue-400">SMES</span>
              </span>
              <p className="text-[10px] font-medium tracking-wider text-zinc-400 uppercase">
                Smart Execution System
              </p>
            </div>
          </Link>
          <button
            onClick={() => setSidebarOpen(false)}
            className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Quick Action Floor Badge */}
        <div className="p-4 border-b border-zinc-100 dark:border-zinc-800/50">
          <Link
            href="/production/move"
            className="flex items-center justify-between rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 p-3 text-white shadow-sm hover:opacity-95 transition-opacity"
          >
            <div className="flex items-center gap-2.5">
              <ArrowRightLeft className="h-4 w-4" />
              <span className="text-xs font-semibold">Move Parts on Floor</span>
            </div>
            <span className="rounded-md bg-white/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider">
              Scan
            </span>
          </Link>
        </div>

        {/* Navigation Items */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
          {visibleNavGroups.map((grp) => (
            <div key={grp.group}>
              <h4 className="px-3 text-[10px] font-bold tracking-wider text-zinc-400 uppercase">
                {grp.group}
              </h4>
              <div className="mt-1.5 space-y-0.5">
                {grp.items.map((item) => {
                  const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setSidebarOpen(false)}
                      className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium transition-all ${
                        isActive
                          ? "bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400 font-semibold shadow-xs"
                          : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        {item.icon}
                        <span>{item.name}</span>
                      </div>
                      {item.badge && (
                        <span className="rounded-md bg-purple-500/10 text-purple-600 dark:text-purple-400 px-1.5 py-0.5 text-[9px] font-bold uppercase">
                          {item.badge}
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Footer / User Role Switcher */}
        <div className="border-t border-zinc-200 dark:border-zinc-800 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 font-bold text-xs">
                PM
              </div>
              <div className="overflow-hidden">
                <p className="truncate text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Production Mgr
                </p>
                <p className="text-[10px] text-zinc-500 dark:text-zinc-400">
                  pm@vspl.com
                </p>
              </div>
            </div>
            <button
              onClick={logout}
              title="Logout"
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200 transition-colors"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col lg:pl-72">
        {/* Top Navbar */}
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 px-6 backdrop-blur">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setSidebarOpen(true)}
              className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 lg:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <Factory className="h-4 w-4 text-blue-600" />
              <span>Plant 1 (Foundry & CNC)</span>
              <span className="text-zinc-300 dark:text-zinc-700">•</span>
              <span className="rounded-full bg-emerald-500/10 text-emerald-600 px-2 py-0.5 text-[10px] font-bold">
                OMS Engine v3.3
              </span>
            </div>
          </div>

          {/* Top Actions */}
          <div className="flex items-center gap-3">
            {/* AI Assistant Button */}
            <Link
              href="/ai"
              className="hidden sm:flex items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs font-semibold text-purple-600 dark:text-purple-400 hover:bg-purple-500/20 transition-colors"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>Ask AI Intelligence</span>
            </Link>

            {/* Dark Mode Toggle */}
            <button
              onClick={toggleDarkMode}
              className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200 transition-colors"
              title="Toggle theme"
            >
              {darkMode ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            {/* Notification Badge */}
            <div className="relative">
              <button
                onClick={() => setShowNotifications(!showNotifications)}
                className="relative rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200 transition-colors"
              >
                <Bell className="h-4 w-4" />
                {notificationCount > 0 && (
                  <span className="absolute top-1.5 right-1.5 flex h-2 w-2 rounded-full bg-rose-500 ring-2 ring-white dark:ring-zinc-900" />
                )}
              </button>

              {/* Proactive Notification Dropdown */}
              {showNotifications && (
                <div className="absolute right-0 mt-2 w-80 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-xl z-50">
                  <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-2">
                    <h5 className="text-xs font-bold text-zinc-900 dark:text-zinc-100">Live AI Insights</h5>
                    <span className="text-[10px] text-zinc-400">3 Alerts</span>
                  </div>
                  <div className="mt-3 space-y-2.5">
                    <div className="rounded-lg bg-rose-50 dark:bg-rose-950/40 p-2.5 border border-rose-200 dark:border-rose-900/50">
                      <p className="text-xs font-bold text-rose-700 dark:text-rose-400">WO-1005 Overdue</p>
                      <p className="text-[11px] text-rose-600 dark:text-rose-300">2 days overdue at FI stage for HAL Aerospace.</p>
                    </div>
                    <div className="rounded-lg bg-amber-50 dark:bg-amber-950/40 p-2.5 border border-amber-200 dark:border-amber-900/50">
                      <p className="text-xs font-bold text-amber-700 dark:text-amber-400">F2 Machining Buffer High</p>
                      <p className="text-[11px] text-amber-600 dark:text-amber-300">480 pieces waiting at CNC Lathe 01.</p>
                    </div>
                    <div className="rounded-lg bg-blue-50 dark:bg-blue-950/40 p-2.5 border border-blue-200 dark:border-blue-900/50">
                      <p className="text-xs font-bold text-blue-700 dark:text-blue-400">Packing Queue Update</p>
                      <p className="text-[11px] text-blue-600 dark:text-blue-300">200 pieces ready for dispatch in bay.</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Dynamic Page Content */}
        <main className="flex-1 p-6 md:p-8 max-w-7xl w-full mx-auto">{children}</main>
      </div>
    </div>
  );
}
