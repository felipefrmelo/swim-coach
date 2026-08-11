import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Check, Goal as GoalIcon, MapPin, Sparkles, Waves } from "lucide-react";

import { api } from "../api/client";
import type { Goal, Me } from "../api/types";
import { ErrorState, LoadingState, SavedNotice } from "../components/AsyncState";

export function DashboardPage() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const pools = useQuery({ queryKey: ["pools"], queryFn: api.pools });
  const goals = useQuery({ queryKey: ["goals"], queryFn: api.goals });
  const availability = useQuery({ queryKey: ["availability"], queryFn: api.availability });
  if (me.isLoading || pools.isLoading || goals.isLoading || availability.isLoading) return <LoadingState />;
  if (!me.data || !pools.data || !goals.data || !availability.data) return <ErrorState message="Seu contexto não pôde ser carregado." />;
  const defaultPool = pools.data.find((pool) => pool.is_default);
  const primaryGoal = goals.data.find((goal) => goal.status === "active");
  const contextComplete = availability.data.length > 0;
  return (
    <div className="page-stack">
      <section>
        <p className="eyebrow">Fundação pronta · P01</p>
        <h1 className="page-title">Seu ponto de partida</h1>
        <p className="page-copy">Contexto confiável para os próximos treinos, sem depender da memória da conversa.</p>
      </section>
      <section className="grid gap-4 sm:grid-cols-2" aria-label="Resumo do contexto">
        <article className="metric-card bg-cyan-950 text-white">
          <Waves className="size-6 text-cyan-300" aria-hidden="true" />
          <div><p className="metric-value">{defaultPool?.length_m ?? "—"}<span className="metric-unit"> m</span></p><p className="metric-label">Piscina principal</p></div>
        </article>
        <article className="metric-card">
          <GoalIcon className="size-6 text-orange-600" aria-hidden="true" />
          <div><p className="metric-value">{primaryGoal?.target_distance_m.toLocaleString("pt-BR") ?? "—"}<span className="metric-unit"> m</span></p><p className="metric-label">Meta em 45 minutos</p></div>
        </article>
      </section>
      <section className="surface-card">
        <div className="flex items-start gap-4"><span className="icon-chip"><Sparkles className="size-5" /></span><div><h2 className="section-title">{contextComplete ? "Contexto inicial completo" : "Seu contexto está quase pronto"}</h2><p className="mt-2 text-sm leading-6 text-slate-600">{contextComplete ? "Perfil, piscina, disponibilidade e meta estão isolados na sua conta." : "Perfil, piscina e meta já estão isolados na sua conta. Configure a disponibilidade para fechar esta etapa."}</p></div></div>
        <div className="mt-6 grid gap-3">
          {["Perfil local autenticado", `Piscina padrão de ${defaultPool?.length_m ?? "—"} m`, ...(contextComplete ? ["Disponibilidade semanal registrada"] : []), `Meta de ${(primaryGoal?.target_distance_m ?? 0).toLocaleString("pt-BR")} m em 45 min`].map((item) => <p className="check-row" key={item}><Check className="size-4" />{item}</p>)}
        </div>
      </section>
      <section className="empty-card"><CalendarPlus className="size-7 text-cyan-800" /><div><h2 className="section-title">Nenhum treino agendado ainda</h2><p className="mt-2 text-sm leading-6 text-slate-600">O editor e o calendário de treinos entram no P04. Aqui mostramos somente fatos já disponíveis.</p></div></section>
    </div>
  );
}

export function ProfilePage() {
  const queryClient = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  if (!me) return <LoadingState label="Carregando perfil…" />;
  return <ProfileForm me={me} onSaved={async () => queryClient.invalidateQueries({ queryKey: ["me"] })} />;
}

function ProfileForm({ me, onSaved }: { me: Me; onSaved: () => Promise<unknown> }) {
  const [displayName, setDisplayName] = useState(me.user.display_name);
  const [sessions, setSessions] = useState(me.profile.default_sessions_per_week);
  const [experience, setExperience] = useState(me.profile.experience_level);
  const mutation = useMutation({
    mutationFn: () => api.updateProfile({ display_name: displayName, locale: me.user.locale, timezone: me.user.timezone, experience_level: experience, default_sessions_per_week: sessions, version: me.profile.version }),
    onSuccess: onSaved,
  });
  return <Page title="Perfil" eyebrow="Preferências do atleta"><form className="surface-card form-stack" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}><Field label="Como quer ser chamado"><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required /></Field><Field label="Experiência"><select value={experience} onChange={(event) => setExperience(event.target.value)}><option value="beginner">Iniciante</option><option value="recreational">Recreativo</option><option value="intermediate">Intermediário</option><option value="advanced">Avançado</option></select></Field><Field label="Sessões por semana"><input type="number" min="1" max="14" value={sessions} onChange={(event) => setSessions(Number(event.target.value))} /></Field>{mutation.isError && <ErrorState message="Revise os dados e tente novamente." />}{mutation.isSuccess && <SavedNotice>Perfil atualizado com auditoria.</SavedNotice>}<SubmitButton pending={mutation.isPending}>Salvar perfil</SubmitButton></form></Page>;
}

export function PoolsPage() {
  const queryClient = useQueryClient();
  const pools = useQuery({ queryKey: ["pools"], queryFn: api.pools });
  const [name, setName] = useState("Piscina alternativa");
  const [length, setLength] = useState(25);
  const create = useMutation({ mutationFn: () => api.createPool({ name, length_m: length, is_default: false, location_label: null }), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["pools"] }) });
  if (pools.isLoading) return <LoadingState label="Carregando piscinas…" />;
  if (!pools.data) return <ErrorState message="Não foi possível carregar as piscinas." />;
  return <Page title="Piscinas" eyebrow="Distâncias sem unidade implícita"><div className="grid gap-4">{pools.data.map((pool) => <article className="surface-card flex items-center gap-4" key={pool.id}><span className="icon-chip"><MapPin className="size-5" /></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="section-title">{pool.name}</h2>{pool.is_default && <span className="badge">Padrão</span>}</div><p className="mt-1 text-sm text-slate-600">{pool.length_m} metros · {pool.active ? "ativa" : "inativa"}</p></div></article>)}<form className="surface-card form-stack" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}><h2 className="section-title">Adicionar piscina</h2><Field label="Nome"><input value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label="Comprimento em metros"><input type="number" min="1" max="100" value={length} onChange={(event) => setLength(Number(event.target.value))} /></Field>{create.isSuccess && <SavedNotice>Nova piscina adicionada.</SavedNotice>}<SubmitButton pending={create.isPending}>Adicionar piscina</SubmitButton></form></div></Page>;
}

export function AvailabilityPage() {
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: ["availability"], queryFn: api.availability });
  const replace = useMutation({ mutationFn: () => api.replaceAvailability([{ day_of_week: 1, start_local_time: "19:00:00", end_local_time: "20:00:00", max_duration_minutes: 60, pool_id: null, valid_from: null, valid_until: null, priority: 0 }]), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["availability"] }) });
  if (rules.isLoading) return <LoadingState label="Carregando disponibilidade…" />;
  if (!rules.data) return <ErrorState message="Não foi possível carregar sua disponibilidade." />;
  return <Page title="Disponibilidade" eyebrow="Agenda recorrente">{rules.data.length === 0 ? <section className="empty-card"><CalendarPlus className="size-7 text-cyan-800" /><div><h2 className="section-title">Sua agenda ainda está vazia</h2><p className="mt-2 text-sm leading-6 text-slate-600">Comece com uma janela simples e ajuste quando sua rotina mudar.</p><button className="primary-button mt-6" type="button" onClick={() => replace.mutate()} disabled={replace.isPending}>Adicionar terça, 19h–20h</button></div></section> : <div className="grid gap-4">{rules.data.map((rule) => <article className="surface-card" key={rule.id}><p className="eyebrow">Terça-feira</p><p className="metric-value mt-3">{rule.start_local_time.slice(0, 5)}–{rule.end_local_time.slice(0, 5)}</p><p className="metric-label">Até {rule.max_duration_minutes} minutos</p></article>)}</div>}</Page>;
}

export function GoalsPage() {
  const queryClient = useQueryClient();
  const goals = useQuery({ queryKey: ["goals"], queryFn: api.goals });
  if (goals.isLoading) return <LoadingState label="Carregando meta…" />;
  if (!goals.data) return <ErrorState message="Não foi possível carregar sua meta." />;
  if (goals.data.length === 0) return <Page title="Meta" eyebrow="Direção do treino"><section className="empty-card"><GoalIcon className="size-7" /><div><h2 className="section-title">Defina sua primeira meta</h2><p className="mt-2 text-sm text-slate-600">Distância e tempo geram um ritmo-alvo explícito.</p></div></section></Page>;
  return <GoalEditor goal={goals.data[0]} onSaved={async () => queryClient.invalidateQueries({ queryKey: ["goals"] })} />;
}

function GoalEditor({ goal, onSaved }: { goal: Goal; onSaved: () => Promise<unknown> }) {
  const [distance, setDistance] = useState(goal.target_distance_m);
  const [durationMinutes, setDurationMinutes] = useState(Number(goal.target_duration_seconds) / 60);
  const mutation = useMutation({ mutationFn: () => api.updateGoal({ ...goal, target_distance_m: distance, target_duration_seconds: String(durationMinutes * 60) }), onSuccess: onSaved });
  return <Page title="Meta" eyebrow="Ritmo calculado no domínio"><form className="surface-card form-stack" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}><div className="rounded-3xl bg-cyan-950 p-6 text-white"><p className="text-sm text-cyan-200">Ritmo-alvo atual</p><p className="metric-value mt-2">{Math.round(Number(goal.target_pace_seconds_per_100m) / 60)}:{String(Math.round(Number(goal.target_pace_seconds_per_100m) % 60)).padStart(2, "0")}<span className="metric-unit"> /100 m</span></p></div><Field label="Distância-alvo (m)"><input type="number" min="1" value={distance} onChange={(event) => setDistance(Number(event.target.value))} /></Field><Field label="Tempo-alvo (min)"><input type="number" min="1" value={durationMinutes} onChange={(event) => setDurationMinutes(Number(event.target.value))} /></Field>{mutation.isSuccess && <SavedNotice>Meta recalculada e salva.</SavedNotice>}<SubmitButton pending={mutation.isPending}>Salvar meta</SubmitButton></form></Page>;
}

function Page({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) { return <div className="page-stack"><section><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1></section>{children}</div>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="grid gap-2 text-sm font-semibold text-slate-700"><span>{label}</span>{children}</label>; }
function SubmitButton({ pending, children }: { pending: boolean; children: string }) { return <button className="primary-button" disabled={pending} type="submit">{pending ? "Salvando…" : children}</button>; }
