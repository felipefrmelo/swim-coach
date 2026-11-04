import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { CoachingOverview } from "../api/types";

const states: Record<string, string> = {
  ACTIVE: "Em andamento", PAUSED: "Pausado", COMPLETED: "Concluído", SUPERSEDED: "Ciclo anterior",
  ENDED_NEEDS_REVIEW: "Encerrado aguardando decisão", CANCELLED: "Cancelado", DRAFT: "Proposta",
  PUBLISHED: "Garmin confirmado", QUEUED: "Na fila do Garmin", PROCESSING: "Enviando ao Garmin",
  RETRYING: "Nova tentativa agendada", FAILED: "Falha no envio", OUT_OF_SYNC: "Reconciliar Garmin", NOT_PUBLISHED: "Ainda não enviado",
};
const dateLabel = (date: string) => date.split("-").reverse().join("/");

export function CoachingPanel() {
  const overview = useQuery({ queryKey: ["coaching"], queryFn: api.coachingOverview });
  const data = overview.data;
  const ids = data?.agenda?.filter((w) => !w.completed).slice(0, 14).map((w) => w.workout_id) ?? [];
  const status = useQuery({ queryKey: ["coaching-publication", ids], queryFn: () => api.coachingPublication(ids), enabled: ids.length > 0, refetchInterval: 30000 });
  if (!data?.cycles) return <section className="surface-card"><h2 className="section-title">Ciclo e agenda</h2><p className="mt-2 text-sm text-slate-600">{overview.isError ? "Não foi possível consultar a agenda. Tente atualizar a página." : "Carregando ciclo e agenda…"}</p></section>;
  return <section className="surface-card form-stack" aria-label="Ciclo e agenda">
    <h2 className="section-title">Ciclo e agenda</h2>
    {data.cycles.slice(0, 3).map((cycle) => <article key={cycle.plan_id} className="rounded-xl bg-slate-50 p-4">
      <p className="font-semibold">{states[cycle.lifecycle_state] ?? cycle.lifecycle_state}</p><p>{cycle.title}</p>
      <a href="/plans" className="secondary-button mt-3">Visualizar e editar planos</a>
      {cycle.goal_relationship !== "CURRENT" && <p className="mt-1 text-sm text-amber-900">Ciclo baseado em meta anterior ou sem snapshot histórico verificado. A meta vigente aparece acima.</p>}
      {cycle.lifecycle_state === "ENDED_NEEDS_REVIEW" && <p className="mt-2 text-sm">Peça ao treinador uma proposta de próximo ciclo. Seu histórico será preservado.</p>}
    </article>)}
    {data.next_workout && <p className="text-sm"><strong>Próxima sessão:</strong> {data.next_workout.title} · {dateLabel(data.next_workout.scheduled_date ?? "")} às {data.next_workout.scheduled_start_time ?? "horário a definir"}</p>}
    <p className="text-xs text-slate-500">Horários em {data.timezone}. Publicação só é confirmada após resposta do Garmin.</p>
    {data.agenda.filter((w) => w.scheduled_date && w.scheduled_date >= data.local_date).slice(0, 14).map((workout) => {
      const remote = status.data?.items.find((i) => i.workout_id === workout.workout_id);
      return <article className="rounded-xl border border-slate-200 p-4" key={workout.workout_id}>
        <p className="font-semibold">{dateLabel(workout.scheduled_date ?? "")} · {workout.scheduled_start_time ?? "—"} · {workout.title}</p>
        <p className="mt-1 text-sm">Planejado: {workout.distance_m ?? "—"} m · piscina {workout.pool_length_m ?? "—"} m · {workout.completed ? "Realizado" : "Planejado"}</p>
        {workout.recorded_distance_m != null && <p className="mt-1 text-sm">Registrado pelo Garmin: {workout.recorded_distance_m} m</p>}
        {workout.athlete_confirmed_distance_m != null && <p className="mt-1 text-sm">Confirmado pelo atleta: {workout.athlete_confirmed_distance_m} m</p>}
        {workout.performance_blocked && <p className="mt-1 text-sm text-amber-900">Medição contestada; não usar o ritmo registrado para progressão.</p>}
        <p className="mt-1 text-sm">{workout.provenance === "PLAN_SESSION" ? "Sessão do ciclo" : workout.provenance === "CONTINGENCY" ? "Retomada avulsa aguardando decisão sobre ciclo" : "Treino avulso"}</p>
        {remote && <p className="mt-1 text-sm font-medium">{states[remote.state] ?? remote.state}{remote.last_verified_at && ` · verificado em ${new Date(remote.last_verified_at).toLocaleString("pt-BR", { timeZone: data.timezone })}`}</p>}
        {!workout.completed && workout.provenance !== "PLAN_SESSION" && <Reschedule workout={workout} />}
      </article>;
    })}
    {data.pending_jobs.length > 0 && <p role="status" className="text-sm text-amber-900">{data.pending_jobs.length} operação(ões) pendente(s). Consulte Diagnóstico para acompanhar erros e tentativas.</p>}
  </section>;
}

function Reschedule({ workout }: { workout: CoachingOverview["agenda"][number] }) {
  const query = useQueryClient();
  const [date, setDate] = useState(workout.scheduled_date ?? "");
  const [start, setStart] = useState(workout.scheduled_start_time ?? "06:15");
  const [preview, setPreview] = useState<{ calendar_hash: string; sessions: Array<{ scheduled_date: string; conflicts: string[]; available: boolean }> } | null>(null);
  const simulate = useMutation({ mutationFn: () => api.coachingPreview({ requests: [{ period: "ABSOLUTE", local_date: date }], start, workout_id: workout.workout_id }), onSuccess: setPreview });
  const save = useMutation({ mutationFn: () => api.coachingReschedule(workout.workout_id, { request: { period: "ABSOLUTE", local_date: date }, start, expected_version: workout.version, expected_calendar_hash: preview?.calendar_hash ?? "" }), onSuccess: async () => { setPreview(null); await query.invalidateQueries({ queryKey: ["coaching"] }); await query.invalidateQueries({ queryKey: ["coaching-publication"] }); } });
  return <form className="mt-3 grid gap-2" onSubmit={(event) => { event.preventDefault(); simulate.mutate(); }}>
    <label className="text-sm">Nova data<input aria-label={`Nova data para ${workout.title}`} type="date" required value={date} onChange={(e) => { setDate(e.target.value); setPreview(null); }} /></label>
    <label className="text-sm">Horário<input aria-label={`Horário para ${workout.title}`} type="time" required value={start} onChange={(e) => { setStart(e.target.value); setPreview(null); }} /></label>
    <button className="secondary-button" disabled={simulate.isPending} type="submit">Prévia do reagendamento</button>
    {preview && <><p className="text-sm">Mover para {dateLabel(preview.sessions[0].scheduled_date)} às {start}. Se já publicado, o Garmin será reconciliado em segundo plano.</p><button type="button" className="primary-button" disabled={!preview.sessions[0].available || preview.sessions[0].conflicts.length > 0 || save.isPending} onClick={() => save.mutate()}>Confirmar reagendamento</button></>}
    {(simulate.isError || save.isError) && <p role="alert" className="text-sm text-red-800">A agenda pode ter mudado. Atualize a página e gere outra prévia.</p>}
    {save.isSuccess && <p role="status" className="text-sm">Data local atualizada. Acompanhe a confirmação do Garmin.</p>}
  </form>;
}
