import { useMutation, useQuery, useQueryClient, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { ShieldCheck, Waves } from "lucide-react";

import { api, ApiError } from "../api/client";
import { ErrorState, LoadingState } from "../components/AsyncState";
import { router, setAuthenticatedMe } from "../routes/router";

export function App() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 20_000 } } });
  return <QueryClientProvider client={queryClient}><AuthBoundary /></QueryClientProvider>;
}

function AuthBoundary() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["auth-config"], queryFn: api.authConfig });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const devLogin = useMutation({ mutationFn: api.devLogin, onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["me"] }) });
  if (config.isLoading || me.isLoading) return <FullScreen><LoadingState label="Preparando sua raia…" /></FullScreen>;
  if (me.data) { setAuthenticatedMe(me.data); return <RouterProvider router={router} />; }
  if (me.error instanceof ApiError && me.error.status !== 401) return <FullScreen><ErrorState message={me.error.message} /></FullScreen>;
  return <FullScreen><section className="w-full max-w-md rounded-[32px] border border-white/70 bg-white p-8 shadow-[0_24px_80px_rgba(8,47,73,0.16)]"><span className="grid size-14 place-items-center rounded-2xl bg-cyan-950 text-cyan-100"><Waves className="size-7" /></span><p className="eyebrow mt-8">Seu contexto, sua conta</p><h1 className="page-title">Entre no Swim Coach</h1><p className="page-copy">Perfil, piscina e meta ficam isolados e auditáveis. Nenhum token do provedor chega ao navegador.</p><div className="mt-8 rounded-2xl bg-cyan-50 p-4 text-sm text-cyan-950"><p className="flex items-center gap-2 font-semibold"><ShieldCheck className="size-5" />Sessão protegida pelo backend</p></div>{devLogin.isError && <div className="mt-4"><ErrorState message="O login local não foi concluído." /></div>}<button className="primary-button mt-8 w-full" type="button" disabled={devLogin.isPending} onClick={() => config.data?.dev_auth_enabled ? devLogin.mutate() : window.location.assign("/api/v1/auth/login")}>{devLogin.isPending ? "Entrando…" : config.data?.dev_auth_enabled ? "Entrar no ambiente local" : "Continuar com identidade segura"}</button></section></FullScreen>;
}

function FullScreen({ children }: { children: React.ReactNode }) { return <main className="grid min-h-dvh place-items-center bg-[radial-gradient(circle_at_top_right,#cffafe,transparent_38rem)] px-5 py-12">{children}</main>; }
