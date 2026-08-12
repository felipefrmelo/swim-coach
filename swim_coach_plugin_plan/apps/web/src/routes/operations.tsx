import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bell, CheckCircle2, RefreshCw } from "lucide-react";

import { api } from "../api/client";
import { ErrorState, LoadingState } from "../components/AsyncState";

export function OperationsPage() {
  const queryClient = useQueryClient();
  const operations = useQuery({ queryKey: ["operations"], queryFn: api.operations });
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: api.notifications });
  const retry = useMutation({
    mutationFn: api.retryJob,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
  });
  const markRead = useMutation({
    mutationFn: api.readNotification,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  if (operations.isLoading || notifications.isLoading) {
    return <LoadingState label="Lendo as automações…" />;
  }
  if (!operations.data || !notifications.data) {
    return <ErrorState message="Não foi possível carregar as automações." />;
  }
  const metrics = operations.data.metrics;
  return (
    <div className="page-stack">
      <section>
        <p className="eyebrow">P11 · operação pessoal</p>
        <h1 className="page-title">Automações</h1>
        <p className="page-copy">Saúde da fila, falhas recuperáveis e avisos. Publicação e aprovação continuam sempre manuais.</p>
      </section>
      <section className="grid gap-3 sm:grid-cols-3">
        <Metric label="Na fila" value={String((metrics.counts.QUEUED ?? 0) + (metrics.counts.RETRY_SCHEDULED ?? 0))} />
        <Metric label="Mais antigo" value={formatAge(metrics.oldest_active_age_seconds)} />
        <Metric label="Atenção" value={String(metrics.dead_count)} warn={metrics.dead_count > 0} />
      </section>
      <section>
        <div className="mb-4"><p className="eyebrow">Inbox</p><h2 className="section-title mt-2">Notificações</h2></div>
        <div className="grid gap-3">
          {notifications.data.length ? notifications.data.map((item) => (
            <article className="surface-card flex items-start gap-4" key={item.id}>
              <Bell className="size-5 text-cyan-800" />
              <div className="flex-1"><p className="font-semibold">{item.title}</p><p className="mt-1 text-sm text-slate-600">{item.body}</p></div>
              {!item.read_at && <button className="secondary-button" onClick={() => markRead.mutate(item.id)} type="button">Lida</button>}
            </article>
          )) : <p className="text-sm text-slate-500">Nenhuma notificação.</p>}
        </div>
      </section>
      <section>
        <div className="mb-4"><p className="eyebrow">Fila PostgreSQL</p><h2 className="section-title mt-2">Execuções recentes</h2></div>
        <div className="grid gap-3">
          {operations.data.jobs.map((job) => (
            <article className="surface-card flex items-center gap-4" key={job.id}>
              {job.status === "SUCCEEDED" ? <CheckCircle2 className="size-5 text-emerald-700" /> : job.status === "FAILED_TERMINAL" || job.status === "NEEDS_RECONCILIATION" ? <AlertTriangle className="size-5 text-amber-700" /> : <RefreshCw className="size-5 text-cyan-700" />}
              <div className="min-w-0 flex-1"><p className="truncate font-semibold">{job.job_type}</p><p className="mt-1 text-xs text-slate-500">{job.status} · tentativa {job.attempts}/{job.max_attempts}{job.error_code ? ` · ${job.error_code}` : ""}</p></div>
              {job.status === "FAILED_TERMINAL" && job.retryable && <button className="secondary-button" disabled={retry.isPending} onClick={() => retry.mutate(job.id)} type="button">Tentar de novo</button>}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return <article className="surface-card"><p className="text-sm text-slate-500">{label}</p><p className={`mt-2 font-mono text-3xl font-bold ${warn ? "text-amber-700" : "text-cyan-950"}`}>{value}</p></article>;
}

function formatAge(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}min`;
  return `${Math.floor(seconds / 3600)}h`;
}
