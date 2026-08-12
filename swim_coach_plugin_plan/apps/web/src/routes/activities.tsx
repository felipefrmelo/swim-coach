import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, ChevronRight, Gauge, HeartPulse, RefreshCw, ShieldCheck, Timer, Waves } from "lucide-react";

import { api } from "../api/client";
import { saveFeedbackResilient } from "../offline/feedbackQueue";
import type { SwimActivityDetail } from "../api/types";
import { ErrorState, LoadingState, SavedNotice } from "../components/AsyncState";

export function ActivitiesPage() {
  const activities = useQuery({ queryKey: ["activities"], queryFn: api.activities });
  if (activities.isLoading) return <LoadingState label="Organizando suas atividades…" />;
  if (!activities.data) return <ErrorState message="Não foi possível carregar as atividades." />;
  return (
    <Page title="Atividades" eyebrow="Diário de natação · P03">
      <p className="page-copy -mt-4">Dados normalizados e análises reproduzíveis. O arquivo FIT permanece privado no servidor.</p>
      {activities.data.length ? <div className="grid gap-3">{activities.data.map((item) => (
        <Link className="surface-card activity-link" key={item.id} to="/activities/$activityId" params={{ activityId: item.id }}>
          <span className="activity-icon"><Waves className="size-5" /></span>
          <div className="min-w-0 flex-1"><p className="font-semibold text-slate-900">{item.name}</p><p className="mt-1 text-sm text-slate-500">{formatDate(item.start_time_utc)} · {item.pool_length_m ?? 20} m</p></div>
          <div className="text-right"><p className="font-mono text-lg font-bold text-cyan-950">{item.distance_m.toLocaleString("pt-BR")} m</p><p className="text-xs text-slate-500">{formatDuration(item.elapsed_seconds)}</p></div>
          <ChevronRight className="size-5 text-slate-400" />
        </Link>
      ))}</div> : <section className="empty-card"><Waves className="size-7 text-cyan-800" /><div><h2 className="section-title">Seu diário começa no primeiro sync</h2><p className="mt-2 text-sm leading-6 text-slate-600">Conecte a Garmin e importe uma natação para ver séries, ritmo e qualidade dos dados.</p><Link className="primary-button mt-6" to="/garmin">Abrir Garmin</Link></div></section>}
    </Page>
  );
}

export function ActivityDetailPage() {
  const { activityId } = useParams({ strict: false }) as { activityId: string };
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["activity", activityId], queryFn: () => api.activity(activityId), refetchInterval: (query) => query.state.data?.normalized ? false : 5_000 });
  const process = useMutation({ mutationFn: () => api.processActivity(activityId), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["activity", activityId] }) });
  if (detail.isLoading) return <LoadingState label="Calculando a análise…" />;
  if (!detail.data) return <ErrorState message="Não foi possível abrir esta atividade." />;
  const item = detail.data;
  const metrics = item.analysis?.metrics;
  return (
    <Page title={item.activity.name} eyebrow={formatDate(item.activity.start_time_utc)}>
      <section className="activity-hero">
        <div><p className="text-sm text-cyan-100">Distância concluída</p><p className="mt-2 font-mono text-4xl font-bold tracking-tight">{item.activity.distance_m.toLocaleString("pt-BR")}<span className="ml-2 text-base font-medium text-cyan-200">m</span></p></div>
        <div className="activity-hero-grid"><HeroMetric label="Tempo" value={formatDuration(item.activity.elapsed_seconds)} /><HeroMetric label="Ritmo" value={formatPace(metrics?.average_pace_seconds_per_100m)} /></div>
      </section>

      {!item.normalized && <section className="setup-notice"><AlertTriangle className="size-5" /><div className="flex-1"><p className="font-semibold">FIT ainda não normalizado</p><p className="mt-1">O resumo Garmin está seguro. Solicite o processamento para baixar e analisar o arquivo privado.</p><button className="secondary-button mt-4 gap-2" onClick={() => process.mutate()} disabled={process.isPending} type="button"><RefreshCw className={`size-4 ${process.isPending ? "animate-spin" : ""}`} />Processar atividade</button></div></section>}

      {item.analysis && <>
        <section className="grid grid-cols-2 gap-3">
          <Metric icon={Gauge} label="Consistência" value={formatPercent(metrics?.consistency_cv)} detail="CV · menor é melhor" />
          <Metric icon={Timer} label="Descanso" value={formatDuration(metrics?.total_rest_seconds)} detail="entre os blocos" />
          <Metric icon={Activity} label="Fade" value={formatSignedPercent(metrics?.fade_percent)} detail="positivo = desacelerou" />
          <Metric icon={Waves} label="SWOLF" value={formatNumber(metrics?.average_swolf)} detail={`piscina de ${item.activity.pool_length_m ?? 20} m`} />
        </section>
        <section className={`quality-card quality-${item.quality}`}><span className="icon-chip"><ShieldCheck className="size-5" /></span><div><div className="flex flex-wrap items-center gap-2"><h2 className="section-title">Qualidade {qualityLabel(item.quality)}</h2><span className="badge">{Math.round(Number(item.completeness) * 100)}%</span></div><p className="mt-2 text-sm leading-6 text-slate-600">{item.warnings.length ? item.warnings.map(warningLabel).join(" · ") : "Sessão, séries e extensões coerentes para esta análise."}</p><p className="mt-2 text-xs text-slate-400">Parser {item.parser_version}</p></div></section>
      </>}

      <section><div className="mb-4"><p className="eyebrow">Séries detectadas</p><h2 className="section-title mt-2">Como o treino aconteceu</h2></div>{item.intervals.length ? <div className="grid gap-3">{item.intervals.map((interval) => <article className="interval-row" key={interval.index}><div className="interval-index">{interval.index + 1}</div><div className="flex-1"><p className="font-semibold">{interval.distance_m} m · {strokeLabel(interval.stroke_type)}</p><p className="mt-1 text-sm text-slate-500">{formatDuration(interval.duration_seconds)} ativo · {formatDuration(interval.rest_seconds)} descanso</p></div><p className="font-mono text-sm font-bold text-cyan-950">{formatPace(interval.pace_seconds_per_100m)}</p></article>)}</div> : <section className="empty-card"><AlertTriangle className="size-6 text-amber-600" /><p className="text-sm leading-6 text-slate-600">O arquivo não trouxe séries utilizáveis. A qualidade permanece explícita; nada foi inventado.</p></section>}</section>

      <FeedbackCard activityId={activityId} detail={item} />
      <section className="privacy-note"><ShieldCheck className="size-5" /><p>FIT bruto e payload Garmin não são retornados por esta API. Métricas esportivas não são diagnóstico médico.</p></section>
    </Page>
  );
}

function FeedbackCard({ activityId, detail }: { activityId: string; detail: SwimActivityDetail }) {
  const queryClient = useQueryClient();
  const current = detail.feedback;
  const [rpe, setRpe] = useState(current?.rpe ?? 5);
  const [technique, setTechnique] = useState(current?.technique_rating ?? 3);
  const [pain, setPain] = useState(current?.pain_present ?? false);
  const [painLocation, setPainLocation] = useState(current?.pain_location ?? "");
  const [painIntensity, setPainIntensity] = useState(current?.pain_intensity ?? 1);
  const [comment, setComment] = useState(current?.comment ?? "");
  const save = useMutation({
    mutationFn: () => saveFeedbackResilient(activityId, { rpe, technique_rating: technique, fatigue_rating: null, enjoyment_rating: null, pain_present: pain, pain_location: pain ? painLocation : null, pain_intensity: pain ? painIntensity : null, comment: comment || null, version: current?.version ?? null }),
    onSuccess: async (result) => result === "synced" ? queryClient.invalidateQueries({ queryKey: ["activity", activityId] }) : undefined,
  });
  return <section className="surface-card form-stack"><div className="flex gap-4"><span className="icon-chip"><HeartPulse className="size-5" /></span><div><p className="eyebrow">Check-in pós-treino</p><h2 className="section-title mt-2">Como você sentiu a sessão?</h2></div></div><ChoiceRow label="Esforço percebido" values={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]} selected={rpe} onSelect={setRpe} suffix="/10" /><ChoiceRow label="Técnica" values={[1, 2, 3, 4, 5]} selected={technique} onSelect={setTechnique} suffix="/5" /><label className="feedback-toggle"><input checked={pain} onChange={(event) => setPain(event.target.checked)} type="checkbox" /><span><strong>Senti dor</strong><small>Registre o sinal; o app não faz diagnóstico.</small></span></label>{pain && <div className="grid gap-4 sm:grid-cols-2"><label className="grid gap-2 text-sm font-semibold">Local<input value={painLocation} onChange={(event) => setPainLocation(event.target.value)} required /></label><label className="grid gap-2 text-sm font-semibold">Intensidade (1–10)<input min="1" max="10" type="number" value={painIntensity} onChange={(event) => setPainIntensity(Number(event.target.value))} /></label></div>}<label className="grid gap-2 text-sm font-semibold">Nota opcional<input maxLength={2000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Respiração, técnica, sensação…" /></label>{save.isSuccess && <SavedNotice>{save.data === "queued" ? "Feedback guardado neste aparelho; será sincronizado quando a conexão voltar." : "Feedback salvo e análise versionada."}</SavedNotice>}{save.isError && <ErrorState message="Revise o feedback e tente novamente." />}<button className="primary-button" onClick={() => save.mutate()} disabled={save.isPending || (pain && !painLocation.trim())} type="button">{save.isPending ? "Salvando…" : current ? "Atualizar feedback" : "Salvar feedback"}</button></section>;
}

function ChoiceRow({ label, values, selected, onSelect, suffix }: { label: string; values: number[]; selected: number; onSelect: (value: number) => void; suffix: string }) { return <fieldset><legend className="mb-3 text-sm font-semibold text-slate-700">{label} <span className="font-normal text-slate-400">{selected}{suffix}</span></legend><div className="choice-row">{values.map((value) => <button aria-pressed={selected === value} className={selected === value ? "selected" : ""} key={value} onClick={() => onSelect(value)} type="button">{value}</button>)}</div></fieldset>; }
function HeroMetric({ label, value }: { label: string; value: string }) { return <div><p className="text-xs text-cyan-200">{label}</p><p className="mt-1 font-mono text-sm font-bold">{value}</p></div>; }
function Metric({ icon: Icon, label, value, detail }: { icon: typeof Gauge; label: string; value: string; detail: string }) { return <article className="analysis-metric"><Icon className="size-5 text-cyan-700" /><div><p className="font-mono text-xl font-bold tracking-tight">{value}</p><p className="text-xs font-semibold text-slate-600">{label}</p><p className="mt-1 text-[11px] text-slate-400">{detail}</p></div></article>; }
function Page({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) { return <div className="page-stack"><section><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1></section>{children}</div>; }
function formatDate(value: string) { return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function formatDuration(value: unknown) { const seconds = Number(value ?? 0); if (!Number.isFinite(seconds)) return "—"; const minutes = Math.floor(seconds / 60); const rest = Math.round(seconds % 60); return minutes ? `${minutes}min ${rest}s` : `${rest}s`; }
function formatPace(value: unknown) { const seconds = Number(value); if (!Number.isFinite(seconds) || seconds <= 0) return "—"; return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}/100m`; }
function formatPercent(value: unknown) { const number = Number(value); return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "—"; }
function formatSignedPercent(value: unknown) { const number = Number(value); return Number.isFinite(number) ? `${number > 0 ? "+" : ""}${number.toFixed(1)}%` : "—"; }
function formatNumber(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number.toFixed(1) : "—"; }
function qualityLabel(value: SwimActivityDetail["quality"]) { return ({ complete: "alta", partial: "parcial", poor: "limitada" } as Record<string, string>)[value ?? ""] ?? "pendente"; }
function warningLabel(value: string) { return ({ SESSION_LENGTH_DISTANCE_MISMATCH: "distância da sessão divergiu das extensões", LENGTH_MESSAGES_UNAVAILABLE: "extensões ausentes", LAP_MESSAGES_SYNTHESIZED: "série reconstruída do resumo", PACE_SERIES_UNAVAILABLE: "ritmo por série ausente", CONSISTENCY_SAMPLE_INSUFFICIENT: "amostra curta para consistência", FADE_SAMPLE_INSUFFICIENT: "amostra curta para fade", SWOLF_UNAVAILABLE: "SWOLF ausente" } as Record<string, string>)[value] ?? value.toLocaleLowerCase().replaceAll("_", " "); }
function strokeLabel(value: string | null) { return ({ freestyle: "livre", backstroke: "costas", breaststroke: "peito", butterfly: "borboleta", drill: "educativo", mixed: "misto" } as Record<string, string>)[value ?? ""] ?? "nado"; }
