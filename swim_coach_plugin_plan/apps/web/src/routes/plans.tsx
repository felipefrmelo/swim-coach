import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { PlanDefinition, PlanDetail, PlanSession, PlanProposal, WorkoutNode } from "../api/types";
import { NodeEditor } from "./workouts";

const labels: Record<string, string> = { ACTIVE: "Em andamento", PAUSED: "Pausado", COMPLETED: "Concluído", CANCELLED: "Cancelado", SUPERSEDED: "Substituído", DRAFT: "Proposta", ENDED_NEEDS_REVIEW: "Encerrado aguardando revisão", DETAILED: "Detalhada", OUTLINE: "Esboço", STRATEGIC: "Estratégia" };
const dateLabel = (value: string) => value.split("-").reverse().join("/");
const distance = (nodes: WorkoutNode[]): number => nodes.reduce((total, node) => total + (node.type === "repeat" ? node.repetitions * distance(node.children) : node.end_condition.type === "distance" ? node.end_condition.meters : 0), 0);
function errorMessage(error: Error | null) {
  if (error instanceof ApiError && error.status === 409) return "O plano mudou. Recarregue o plano e refaça suas alterações.";
  if (error instanceof ApiError) {
    const issues = error.problem.details?.issues;
    return `${error.message} ${Array.isArray(issues) ? issues.map(issue => typeof issue === "object" && issue && "message" in issue ? String(issue.message) : "").join(" ") : ""}`;
  }
  return error?.message ?? "Não foi possível concluir a operação.";
}

export function PlansPage() {
  const overview = useQuery({ queryKey: ["coaching"], queryFn: api.coachingOverview });
  const [selected, setSelected] = useState("");
  const cycles = overview.data?.cycles ?? [];
  const id = selected || cycles[0]?.plan_id;
  const plan = useQuery({ queryKey: ["plan", id], queryFn: () => api.plan(id!), enabled: !!id });
  return <div className="page-stack">
    <header><p className="eyebrow">Seu ciclo de natação</p><h1 className="page-title">Planos</h1><p className="mt-2 text-slate-600">Consulte cada semana e revise as próximas sessões antes de salvar.</p></header>
    {overview.isPending && <p role="status">Carregando planos…</p>}
    {overview.isError && <p role="alert">Não foi possível consultar os planos. <button onClick={() => overview.refetch()}>Tentar novamente</button></p>}
    {overview.isSuccess && !cycles.length && <section className="surface-card"><h2 className="section-title">Nenhum ciclo disponível</h2><p className="mt-2">Peça ao treinador no ChatGPT uma proposta de plano. Depois de aprovado, ele aparecerá aqui.</p></section>}
    {!!cycles.length && <label className="grid gap-2">Ciclo<select value={id} onChange={e => setSelected(e.target.value)}>{cycles.map(c => <option key={c.plan_id} value={c.plan_id}>{c.title} · {labels[c.lifecycle_state] ?? c.lifecycle_state}</option>)}</select></label>}
    {id && plan.isPending && <p role="status">Carregando semanas…</p>}
    {plan.isError && <p role="alert">Não foi possível abrir este plano. <button onClick={() => plan.refetch()}>Tentar novamente</button></p>}
    {plan.data && <PlanEditor key={`${plan.data.plan_id}-${plan.data.current_revision}`} plan={plan.data} />}
  </div>;
}

export function PlanEditor({ plan }: { plan: PlanDetail }) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState<PlanDefinition | null>(() => structuredClone(plan.definition));
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("");
  const [proposal, setProposal] = useState<PlanProposal | null>(null);
  const [saved, setSaved] = useState(false);
  const propose = useMutation({ mutationFn: () => api.proposePlanEdit(plan.plan_id, { definition: draft!, expected_revision: plan.current_revision, rationale: reason }), onSuccess: setProposal });
  const apply = useMutation({ mutationFn: () => api.applyPlanEdit(plan.plan_id, proposal!), onSuccess: async () => { setSaved(true); setProposal(null); setEditing(false); await cache.invalidateQueries({ queryKey: ["plan", plan.plan_id] }); await cache.invalidateQueries({ queryKey: ["coaching"] }); await cache.invalidateQueries({ queryKey: ["workouts"] }); } });
  if (!draft) return <section className="surface-card">Este ciclo ainda não tem uma revisão aplicada.</section>;
  const editable = plan.status === "ACTIVE" && plan.lifecycle_state !== "ENDED_NEEDS_REVIEW";
  const changed = JSON.stringify(draft) !== JSON.stringify(plan.definition);
  const changedWeeks = draft.weeks.filter((week, i) => JSON.stringify(week) !== JSON.stringify(plan.definition?.weeks[i]));
  const update = (fn: (next: PlanDefinition) => void) => { const next = structuredClone(draft); fn(next); setDraft(next); setProposal(null); setSaved(false); };
  const updateSession = (w: number, s: number, patch: Partial<PlanSession>) => update(next => Object.assign(next.weeks[w].sessions[s], patch));
  return <>
    <section className="surface-card form-stack"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="section-title">{plan.title}</h2><span className="badge">{labels[plan.lifecycle_state] ?? plan.lifecycle_state}</span></div><p>{draft.duration_weeks} semanas · início {dateLabel(draft.start_date)} · {draft.timezone}</p><p>{draft.strategy_summary}</p><p className="text-sm text-slate-500">Revisão {plan.current_revision}. Alterações são salvas no Swim Coach; o Garmin exige envio separado.</p>{editable && !editing && <button className="primary-button" onClick={() => { setEditing(true); setSaved(false); }}>Editar plano</button>}{!editable && <p>Este ciclo está disponível para consulta. Para retomar ou iniciar um sucessor, converse com o treinador.</p>}</section>
    <fieldset className="contents" disabled={propose.isPending || apply.isPending}>
    {draft.weeks.map((week, wi) => {
      const protectedWeek = plan.protected_weeks.includes(week.week_number);
      return <section className="surface-card form-stack" key={week.week_number} aria-label={`Semana ${week.week_number}`}>
        <div className="flex flex-wrap justify-between gap-2"><h2 className="section-title">Semana {week.week_number}</h2><span className="badge">{labels[week.detail_level] ?? week.detail_level}</span></div>
        {editing && !protectedWeek ? <label className="grid gap-2">Foco da semana<input required value={week.focus} onChange={e => update(next => { next.weeks[wi].focus = e.target.value; })} /></label> : <p>{week.focus}</p>}
        {protectedWeek && <p className="text-sm text-slate-500">Semana protegida: histórico preservado.</p>}
        {!week.sessions.length && <p className="text-sm text-slate-500">Sessões ainda não detalhadas. O treinador definirá os exercícios conforme sua evolução.</p>}
        {week.sessions.map((session, si) => {
          const binding = plan.sessions.find(b => b.session_intent_id === session.session_intent_id);
          const locked = protectedWeek || binding?.locked || (!!session.scheduled_date && session.scheduled_date < plan.local_date);
          const canEdit = editing && !locked;
          return <article className="rounded-xl border border-slate-200 p-4 form-stack" key={session.session_intent_id ?? si} aria-label={`Sessão ${session.session_number}`}>
            <h3 className="font-semibold">Sessão {session.session_number} · {session.workout?.title ?? session.purpose}</h3>
            <p className="text-sm">{session.scheduled_date ? dateLabel(session.scheduled_date) : "Data a definir"} · {session.scheduled_start_time ?? "Horário a definir"} · {session.target_distance_m ?? "—"} m · {session.planned_duration_minutes ?? "—"} min{session.workout && ` · piscina ${session.workout.pool_length_m} m`}</p>
            {locked && <p className="text-sm text-amber-900">Sessão protegida ou realizada. Edição indisponível.</p>}
            {canEdit ? <><div className="grid gap-3 sm:grid-cols-2"><label>Data<input type="date" required min={plan.local_date} value={session.scheduled_date ?? ""} onChange={e => updateSession(wi, si, { scheduled_date: e.target.value })} /></label><label>Horário<input type="time" required value={session.scheduled_start_time ?? ""} onChange={e => updateSession(wi, si, { scheduled_start_time: e.target.value })} /></label><label>Duração prevista (min)<input type="number" min="1" max="240" value={session.planned_duration_minutes ?? ""} onChange={e => updateSession(wi, si, { planned_duration_minutes: Number(e.target.value) })} /></label></div><label className="grid gap-2">Objetivo da sessão<textarea value={session.objective ?? ""} onChange={e => updateSession(wi, si, { objective: e.target.value })} /></label><label className="grid gap-2">Notas da sessão<textarea value={session.coach_notes ?? ""} onChange={e => updateSession(wi, si, { coach_notes: e.target.value })} /></label></> : <><p>{session.objective}</p>{session.coach_notes && <p className="text-sm">{session.coach_notes}</p>}</>}
            {session.workout?.nodes.map((node, ni) => canEdit ? <NodeEditor key={ni} node={node} position={ni + 1} poolLength={session.workout!.pool_length_m} first={ni === 0} last={ni === session.workout!.nodes.length - 1} onChange={nextNode => { const workout = structuredClone(session.workout!); workout.nodes[ni] = nextNode; updateSession(wi, si, { workout, target_distance_m: distance(workout.nodes) }); }} onMove={direction => { const workout = structuredClone(session.workout!); [workout.nodes[ni], workout.nodes[ni + direction]] = [workout.nodes[ni + direction], workout.nodes[ni]]; updateSession(wi, si, { workout }); }} onRemove={() => { const workout = structuredClone(session.workout!); workout.nodes.splice(ni, 1); updateSession(wi, si, { workout, target_distance_m: distance(workout.nodes) }); }} /> : <NodeSummary key={ni} node={node} />)}
            {canEdit && session.workout && <button type="button" className="secondary-button" onClick={() => { const workout = structuredClone(session.workout!); workout.nodes.push({ type: "step", step_role: "WORK", end_condition: { type: "distance", meters: workout.pool_length_m * 2 }, stroke: { type: "freestyle" }, target: { type: "none" }, instructions: "" }); updateSession(wi, si, { workout, target_distance_m: distance(workout.nodes) }); }}>Adicionar etapa</button>}
          </article>;
        })}
      </section>;
    })}
    {editing && <section className="surface-card form-stack"><label className="grid gap-2">Motivo da alteração<textarea required maxLength={2000} value={reason} onChange={e => { setReason(e.target.value); setProposal(null); }} /></label><div className="flex flex-wrap gap-3"><button className="primary-button" disabled={!changed || !reason.trim() || propose.isPending || apply.isPending} onClick={() => propose.mutate()}>{propose.isPending ? "Validando…" : "Revisar alterações"}</button><button className="secondary-button" disabled={apply.isPending} onClick={() => { setDraft(structuredClone(plan.definition)); setEditing(false); setProposal(null); propose.reset(); apply.reset(); }}>Cancelar edição</button></div></section>}
    </fieldset>
    {proposal && <section className="surface-card form-stack" aria-label="Confirmar alterações"><h2 className="section-title">Confira antes de salvar</h2><p>Semanas alteradas: {changedWeeks.map(w => w.week_number).join(", ")}.</p>
      {changedWeeks.map(week => <div key={week.week_number} className="rounded-xl bg-slate-50 p-3 text-sm"><p className="font-semibold">Semana {week.week_number}</p><p>Foco anterior: {plan.definition?.weeks.find(w => w.week_number === week.week_number)?.focus}</p><p>Novo foco: {week.focus}</p>{week.sessions.map(session => <p key={session.session_number}>Sessão {session.session_number}: {session.scheduled_date ? dateLabel(session.scheduled_date) : "data a definir"} às {session.scheduled_start_time ?? "—"} · {session.target_distance_m ?? "—"} m · {session.planned_duration_minutes ?? "—"} min</p>)}</div>)}<p>O conteúdo exibido acima será a nova revisão. Seu histórico será preservado. Nenhum treino será enviado ao Garmin.</p><p className="text-sm">Proposta válida até {new Date(proposal.expires_at).toLocaleString("pt-BR", { timeZone: draft.timezone })}.</p><button className="primary-button" disabled={apply.isPending} onClick={() => { if (Date.parse(proposal.expires_at) <= Date.now()) { setProposal(null); propose.reset(); return; } apply.mutate(); }}>{apply.isPending ? "Salvando…" : "Aprovar e salvar revisão"}</button></section>}
    {(propose.isError || apply.isError) && <p role="alert" className="text-red-800">{errorMessage(propose.error ?? apply.error)}</p>}
    {saved && <p role="status">Revisão salva. Os treinos locais serão atualizados em segundo plano.</p>}
    <section className="surface-card form-stack"><h2 className="section-title">Histórico de revisões</h2>{plan.history.map(h => <p key={h.revision}>Revisão {h.revision} · {new Date(h.created_at).toLocaleDateString("pt-BR", { timeZone: draft.timezone })} · {h.reason}</p>)}</section>
  </>;
}

function NodeSummary({ node }: { node: WorkoutNode }) {
  if (node.type === "repeat") return <div className="rounded-xl bg-slate-50 p-3"><p className="font-semibold">{node.repetitions}× {node.label ?? "Repetição"}</p>{node.children.map((child, i) => <NodeSummary key={i} node={child} />)}</div>;
  const target = node.target;
  return <div className="rounded-xl bg-slate-50 p-3 text-sm"><p className="font-semibold">{node.label ?? node.step_role} · {node.end_condition.type === "distance" ? `${node.end_condition.meters} m` : node.end_condition.type === "time" ? `${node.end_condition.seconds} s` : "Botão lap"}</p>{target?.type === "rpe" && <p>RPE {target.min}–{target.max}</p>}{target?.type === "pace_range" && <p>Ritmo {target.min_seconds_per_100m}–{target.max_seconds_per_100m} s/100 m</p>}{node.instructions && <p className="mt-1">{node.instructions}</p>}</div>;
}
