import {
  CalendarDays,
  Activity,
  CircleUserRound,
  Goal,
  Home,
  LogOut,
  MapPin,
  NotebookPen,
  Watch,
  Waves,
  WifiOff,
  Bell,
  type LucideIcon,
} from "lucide-react";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Me } from "../api/types";

interface NavigationItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const navigation: NavigationItem[] = [
  { to: "/", label: "Início", icon: Home },
  { to: "/workouts", label: "Treinos", icon: NotebookPen },
  { to: "/calendar", label: "Calendário", icon: CalendarDays },
  { to: "/activities", label: "Atividades", icon: Activity },
  { to: "/pools", label: "Piscinas", icon: MapPin },
  { to: "/availability", label: "Agenda", icon: CalendarDays },
  { to: "/goals", label: "Meta", icon: Goal },
  { to: "/garmin", label: "Garmin", icon: Watch },
  { to: "/operations", label: "Automações", icon: Bell },
  { to: "/profile", label: "Perfil", icon: CircleUserRound },
];

export function AppShell({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const [offline, setOffline] = useState(!navigator.onLine);
  const [stale, setStale] = useState(false);
  const [feedbackConflict, setFeedbackConflict] = useState(false);
  useEffect(() => {
    const online = () => { setOffline(false); setStale(false); };
    const offlineNow = () => setOffline(true);
    const feedbackNeedsReview = () => setFeedbackConflict(true);
    const message = (event: MessageEvent<{ type?: string }>) => {
      if (event.data?.type === "SWIM_COACH_STALE_DATA") setStale(true);
    };
    window.addEventListener("online", online);
    window.addEventListener("offline", offlineNow);
    window.addEventListener("swim-coach:feedback-conflict", feedbackNeedsReview);
    navigator.serviceWorker?.addEventListener("message", message);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offlineNow);
      window.removeEventListener("swim-coach:feedback-conflict", feedbackNeedsReview);
      navigator.serviceWorker?.removeEventListener("message", message);
    };
  }, []);
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      await queryClient.invalidateQueries();
      window.location.assign("/");
    },
  });

  return (
    <div className="min-h-dvh bg-slate-50 text-slate-950">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-slate-200 bg-white p-6 lg:flex lg:flex-col">
        <Brand />
        <nav className="mt-12 grid gap-2" aria-label="Navegação principal">
          {navigation.map((item) => (
            <NavItem key={item.to} item={item} active={pathname === item.to} />
          ))}
        </nav>
        <button className="nav-button mt-auto" onClick={() => logout.mutate()} type="button">
          <LogOut className="size-5" aria-hidden="true" />
          Sair
        </button>
      </aside>

      <div className="mx-auto min-h-dvh max-w-5xl pb-28 lg:ml-64 lg:pb-8">
        {(offline || stale || feedbackConflict) && <div className="flex items-center justify-center gap-2 bg-amber-100 px-4 py-2 text-sm font-semibold text-amber-950" role="status"><WifiOff className="size-4" />{feedbackConflict ? "Um feedback offline precisa ser revisado antes de sincronizar." : stale ? "Dados offline podem estar desatualizados. Ações sensíveis exigem conexão." : "Você está offline. Feedbacks serão enviados quando a conexão voltar."}</div>}
        <header className="flex items-center justify-between px-5 pb-4 pt-6 sm:px-8 lg:px-12 lg:pt-10">
          <div className="lg:hidden"><Brand /></div>
          <div className="ml-auto text-right">
            <p className="text-sm text-slate-500">Contexto pessoal</p>
            <p className="font-semibold">{me.user.display_name}</p>
          </div>
        </header>
        <main className="px-5 sm:px-8 lg:px-12"><Outlet /></main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 flex overflow-x-auto border-t border-slate-200 bg-white/95 px-2 pb-[max(8px,env(safe-area-inset-bottom))] pt-2 shadow-[0_-12px_32px_rgba(8,47,73,0.08)] backdrop-blur lg:hidden" aria-label="Navegação principal">
        {navigation.map((item) => (
          <NavItem key={item.to} item={item} active={pathname === item.to} compact />
        ))}
      </nav>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <span className="grid size-11 place-items-center rounded-2xl bg-cyan-950 text-cyan-100 shadow-[0_12px_30px_rgba(8,47,73,0.18)]">
        <Waves className="size-6" aria-hidden="true" />
      </span>
      <div>
        <p className="font-semibold tracking-tight">Swim Coach</p>
        <p className="text-xs text-slate-500">Base de treino</p>
      </div>
    </div>
  );
}

function NavItem({ item, active, compact = false }: { item: NavigationItem; active: boolean; compact?: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      className={compact ? `mobile-nav min-w-[72px] flex-1 ${active ? "mobile-nav-active" : ""}` : `nav-button ${active ? "nav-button-active" : ""}`}
      aria-current={active ? "page" : undefined}
    >
      <Icon className="size-5" aria-hidden="true" />
      <span>{item.label}</span>
    </Link>
  );
}
