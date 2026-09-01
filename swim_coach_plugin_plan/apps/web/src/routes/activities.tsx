import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, ChevronRight, Gauge, HeartPulse, RefreshCw, ShieldCheck, Timer, Waves } from "lucide-react";

import { api } from "../api/client";
import { saveFeedbackResilient } from "../offline/feedbackQueue";
import type { SwimActivityDetailV2 } from "../api/types";
import { ErrorState, LoadingState, SavedNotice } from "../components/AsyncState";

export function ActivitiesPage() {
  const activities = useQuery({ queryKey: ["activities"], queryFn: api.activities });
  if (activities.isLoading) return <LoadingState label="Organizando suas atividades…" />;
  if (!activities.data) return <ErrorState message="Não foi possível carregar as atividades." />;
  return (
    <Page title="Atividades" eyebrow="Diário de natação · P03">
      <p className="page-copy -mt-4">Dados normalizados e análises reproduzíveis. O arquivo FIT permanece privado no servidor.</p>
      {activities.data.length ? <div className="grid gap-3">{activities.data.map((item) => (
        <Link className="surface-card activity-link" key={item.activity_id} to="/activities/$activityId" params={{ activityId: item.activity_id }}>
          <span className="activity-icon"><Waves className="size-5" /></span>
          <div className="min-w-0 flex-1"><p className="font-semibold text-slate-900">{item.name}</p><p className="mt-1 text-sm text-slate-500">{formatDate(item.started_at_local, item.timezone)} · {poolLabel(item.pool.length_m)}</p></div>
          <div className="text-right"><p className="font-mono text-lg font-bold text-cyan-950">{item.distance_m.toLocaleString("pt-BR")} m</p><p className="text-xs text-slate-500">{formatDuration(item.durations.elapsed_s)}</p></div>
          <ChevronRight className="size-5 text-slate-400" />
        </Link>
      ))}</div> : <section className="empty-card"><Waves className="size-7 text-cyan-800" /><div><h2 className="section-title">Seu diário começa no primeiro sync</h2><p className="mt-2 text-sm leading-6 text-slate-600">Conecte a Garmin e importe uma natação para ver séries, ritmo e qualidade dos dados.</p><Link className="primary-button mt-6" to="/garmin">Abrir Garmin</Link></div></section>}
    </Page>
  );
}

export function ActivityDetailPage() {
  const { activityId } = useParams({ strict: false }) as { activityId: string };
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["activity", activityId], queryFn: () => api.activity(activityId), refetchInterval: (query) => query.state.data?.normalization ? false : 5_000 });
  const process = useMutation({ mutationFn: () => api.processActivity(activityId), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["activity", activityId] }) });
  if (detail.isLoading) return <LoadingState label="Calculando a análise…" />;
  if (!detail.data) return <ErrorState message="Não foi possível abrir esta atividade." />;
  const item = detail.data;
  const metrics = item.analysis?.metrics;
  const efficiency = firstStrokeEfficiency(metrics);
  const representativeSet = firstFreestyleWorkSet(metrics);
  const analyzedRest = analysisDuration(metrics, "rest_s");
  const restUsesPlannedContext = item.analysis?.flags.includes("REST_CLASSIFIED_FROM_PLANNED_WORKOUT") ?? false;
  return (
    <Page title={item.name} eyebrow={formatDate(item.started_at_local, item.timezone)}>
      <section className="activity-hero">
        <div><p className="text-sm text-cyan-100">Distância concluída</p><p className="mt-2 font-mono text-4xl font-bold tracking-tight">{item.distance_m.toLocaleString("pt-BR")}<span className="ml-2 text-base font-medium text-cyan-200">m</span></p></div>
        <div className="activity-hero-grid"><HeroMetric label="Tempo da sessão (elapsed)" value={formatDuration(item.durations.elapsed_s)} /><HeroMetric label="Ritmo nadando (moving)" value={formatPace(item.paces.moving_s_per_100m)} /><HeroMetric label="Ritmo por extensões ativas" value={formatPace(item.paces.swim_s_per_100m)} /><HeroMetric label="Ritmo da sessão (elapsed)" value={formatPace(item.paces.session_s_per_100m)} /></div>
      </section>

      {!item.normalization && <section className="setup-notice"><AlertTriangle className="size-5" /><div className="flex-1"><p className="font-semibold">FIT ainda não normalizado</p><p className="mt-1">O resumo Garmin está seguro. Solicite o processamento para baixar e analisar o arquivo privado.</p><button className="secondary-button mt-4 gap-2" onClick={() => process.mutate()} disabled={process.isPending} type="button"><RefreshCw className={`size-4 ${process.isPending ? "animate-spin" : ""}`} />Processar atividade</button></div></section>}

      {item.analysis && <>
        <section className="grid grid-cols-2 gap-3">
          <Metric icon={Gauge} label="Consistência" value={formatPercent(representativeSet?.coefficient_of_variation)} detail="CV do set equivalente · menor é melhor" />
          <Metric icon={Timer} label={restUsesPlannedContext ? "Descanso contextual" : "Descanso explícito"} value={formatDuration(analyzedRest ?? item.durations.rest_s)} detail={restUsesPlannedContext ? "combina evidência FIT com REST alinhado ao planejamento; demais paradas não são assumidas" : "confirmado por extensões IDLE no FIT normalizado"} />
          <Metric icon={Activity} label="Fade" value={formatSignedPercent(representativeSet?.fade_percent)} detail="set equivalente · positivo = desacelerou" />
          <Metric icon={Waves} label="SWOLF contextual" value={formatNumber(efficiency?.average_swolf)} detail={`${strokeLabel(typeof efficiency?.stroke === "string" ? efficiency.stroke : null)} · ${poolLabel(item.pool.length_m)} · compare apenas ritmos semelhantes`} />
        </section>
        <section className={`quality-card quality-${item.data_quality.level.toLowerCase()}`}><span className="icon-chip"><ShieldCheck className="size-5" /></span><div><div className="flex flex-wrap items-center gap-2"><h2 className="section-title">Qualidade {qualityLabel(item.data_quality.level)}</h2><span className="badge">{Math.round(Number(item.normalization?.completeness ?? 0) * 100)}%</span></div><p className="mt-2 text-sm leading-6 text-slate-600">{item.data_quality.reasons.length ? item.data_quality.reasons.map(warningLabel).join(" · ") : "Sessão, séries e extensões coerentes para esta análise."}</p><p className="mt-2 text-xs text-slate-400">Parser {item.normalization?.parser_version}</p></div></section>
      </>}

      <section><div className="mb-4"><p className="eyebrow">Séries detectadas</p><h2 className="section-title mt-2">Como o treino aconteceu</h2></div>{item.intervals.length ? <div className="grid gap-3">{item.intervals.map((interval) => <article className="interval-row" key={interval.index}><div className="interval-index">{interval.index + 1}</div><div className="flex-1"><p className="font-semibold">{intervalTitle(interval)}</p><p className="mt-1 text-sm text-slate-500">{intervalDetail(interval)}</p></div><p className="font-mono text-sm font-bold text-cyan-950">{intervalPace(interval)}</p></article>)}</div> : <section className="empty-card"><AlertTriangle className="size-6 text-amber-600" /><p className="text-sm leading-6 text-slate-600">O arquivo não trouxe séries utilizáveis. A qualidade permanece explícita; nada foi inventado.</p></section>}</section>

      <FeedbackCard activityId={activityId} detail={item} />
      <section className="privacy-note"><ShieldCheck className="size-5" /><p>FIT bruto e payload Garmin não são retornados por esta API. Métricas esportivas não são diagnóstico médico.</p></section>
    </Page>
  );
}

export function FeedbackCard({ activityId, detail }: { activityId: string; detail: SwimActivityDetailV2 }) {
  return <FeedbackCardForm activityId={activityId} detail={detail} key={feedbackFormStateKey(detail)} />;
}

function FeedbackCardForm({ activityId, detail }: { activityId: string; detail: SwimActivityDetailV2 }) {
  const queryClient = useQueryClient();
  const current = detail.feedback;
  const evaluation = detail.session_evaluation;
  const garminRpe = nullableNumber(evaluation.garmin.rpe);
  const manualRpe = current?.rpe ?? evaluation.manual_override.rpe;
  const manualFeeling = current?.feeling_score ?? evaluation.manual_override.feeling_score;
  const [overrideRpe, setOverrideRpe] = useState(manualRpe !== null || garminRpe === null);
  const [overrideFeeling, setOverrideFeeling] = useState(manualFeeling !== null);
  const [rpe, setRpe] = useState<number | null>(manualRpe ?? (garminRpe === null ? null : manualRpeDefault(evaluation.effective.rpe)));
  const [feeling, setFeeling] = useState(manualFeeling ?? evaluation.effective.feeling_score ?? 50);
  const [technique, setTechnique] = useState<number | null>(current?.technique_rating ?? null);
  const [pain, setPain] = useState(current?.pain_present ?? false);
  const [painLocation, setPainLocation] = useState(current?.pain_location ?? "");
  const [painIntensity, setPainIntensity] = useState(current?.pain_intensity ?? 1);
  const [comment, setComment] = useState(current?.comment ?? "");
  const [confirmRemoval, setConfirmRemoval] = useState(false);
  const save = useMutation({
    mutationFn: () => saveFeedbackResilient(activityId, {
      ...(overrideRpe && rpe !== null ? { rpe } : {}),
      ...(overrideFeeling ? { feeling_score: feeling } : {}),
      technique_rating: technique,
      fatigue_rating: null,
      enjoyment_rating: null,
      pain_present: pain,
      pain_location: pain ? painLocation : null,
      pain_intensity: pain ? painIntensity : null,
      comment: comment || null,
      version: current?.version ?? null,
    }),
    onSuccess: async (result) => result === "synced" ? queryClient.invalidateQueries({ queryKey: ["activity", activityId] }) : undefined,
  });
  const removeFeedback = useMutation({
    mutationFn: () => saveFeedbackResilient(activityId, {
      technique_rating: null,
      fatigue_rating: null,
      enjoyment_rating: null,
      pain_present: false,
      pain_location: null,
      pain_intensity: null,
      comment: null,
      version: current?.version ?? null,
    }),
    onSuccess: async (result) => {
      setConfirmRemoval(false);
      return result === "synced" ? queryClient.invalidateQueries({ queryKey: ["activity", activityId] }) : undefined;
    },
  });
  const hasGarminRpe = garminRpe !== null;
  const hasGarminFeeling = evaluation.garmin.feeling_score !== null;
  const hasManualFeedback = current !== null || (overrideRpe && rpe !== null) || overrideFeeling || technique !== null || pain || comment.trim() !== "";
  return (
    <section className="surface-card form-stack">
      <div className="flex gap-4">
        <span className="icon-chip"><HeartPulse className="size-5" /></span>
        <div><p className="eyebrow">Check-in pós-treino</p><h2 className="section-title mt-2">Avaliação da sessão</h2></div>
      </div>
      <SessionEvaluationSummary evaluation={evaluation} />
      <div className="evaluation-actions">
        {hasGarminRpe
          ? <button aria-pressed={overrideRpe} className="secondary-button" onClick={() => setOverrideRpe((value) => !value)} type="button">{overrideRpe ? "Usar RPE do Garmin" : "Ajustar RPE"}</button>
          : <p className="text-sm leading-6 text-slate-600">O FIT não trouxe esforço. Informe o RPE para completar o check-in.</p>}
        <button aria-pressed={overrideFeeling} className="secondary-button" onClick={() => setOverrideFeeling((value) => !value)} type="button">{overrideFeeling ? (hasGarminFeeling ? "Usar sensação do Garmin" : "Remover sensação") : (hasGarminFeeling ? "Ajustar sensação" : "Informar sensação")}</button>
      </div>
      {overrideRpe && <ChoiceRow label="Esforço percebido manual" values={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]} selected={rpe} onSelect={setRpe} suffix="/10" />}
      {overrideFeeling && <label className="grid gap-2 text-sm font-semibold">Sensação manual <span className="font-normal text-slate-400">{feeling}/100</span><input aria-label="Sensação manual" max="100" min="0" onChange={(event) => setFeeling(Number(event.target.value))} step="1" type="range" value={feeling} /></label>}
      <ChoiceRow label="Técnica (opcional)" values={[1, 2, 3, 4, 5]} selected={technique} onSelect={(value) => setTechnique((selected) => selected === value ? null : value)} suffix="/5" />
      <label className="feedback-toggle"><input checked={pain} onChange={(event) => setPain(event.target.checked)} type="checkbox" /><span><strong>Senti dor</strong><small>Registre o sinal; o app não faz diagnóstico.</small></span></label>
      {pain && <div className="grid gap-4 sm:grid-cols-2"><label className="grid gap-2 text-sm font-semibold">Local<input value={painLocation} onChange={(event) => setPainLocation(event.target.value)} required /></label><label className="grid gap-2 text-sm font-semibold">Intensidade (1–10)<input min="1" max="10" type="number" value={painIntensity} onChange={(event) => setPainIntensity(Number(event.target.value))} /></label></div>}
      <label className="grid gap-2 text-sm font-semibold">Nota opcional<input maxLength={2000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Respiração, técnica, sensação…" /></label>
      {!hasManualFeedback && (hasGarminRpe || hasGarminFeeling) && <p className="text-sm leading-6 text-slate-500" role="status">{importedEvaluationNotice(hasGarminRpe, hasGarminFeeling)}</p>}
      {save.isSuccess && <SavedNotice>{save.data === "queued" ? "Feedback guardado neste aparelho; será sincronizado quando a conexão voltar." : "Feedback salvo e análise versionada."}</SavedNotice>}
      {removeFeedback.isSuccess && <SavedNotice>{removeFeedback.data === "queued" ? "Remoção guardada neste aparelho; será sincronizada quando a conexão voltar." : "Feedback manual removido."}</SavedNotice>}
      {(save.isError || removeFeedback.isError) && <ErrorState message="Revise o feedback e tente novamente." />}
      {confirmRemoval && <section aria-describedby={`remove-feedback-description-${activityId}`} aria-labelledby={`remove-feedback-title-${activityId}`} className="setup-notice" role="alertdialog"><AlertTriangle className="size-5" /><div className="flex-1"><h3 className="font-semibold" id={`remove-feedback-title-${activityId}`}>Remover todo o feedback manual?</h3><p className="mt-1" id={`remove-feedback-description-${activityId}`}>Isso apaga RPE, sensação, técnica, dor e notas manuais desta atividade. {hasGarminRpe || hasGarminFeeling ? "Os valores importados do Garmin permanecem." : "A atividade ficará sem avaliação de esforço ou sensação."}</p><div className="mt-4 grid grid-cols-2 gap-2"><button className="secondary-button" disabled={removeFeedback.isPending} onClick={() => setConfirmRemoval(false)} type="button">Cancelar</button><button className="secondary-button border-rose-200 text-rose-700 hover:bg-rose-50" disabled={removeFeedback.isPending} onClick={() => removeFeedback.mutate()} type="button">{removeFeedback.isPending ? "Removendo…" : "Confirmar remoção"}</button></div></div></section>}
      <button className="primary-button" onClick={() => save.mutate()} disabled={!hasManualFeedback || save.isPending || removeFeedback.isPending || (pain && !painLocation.trim())} type="button">{save.isPending ? "Salvando…" : current ? "Atualizar feedback" : "Salvar feedback"}</button>
      {current && !confirmRemoval && <button className="secondary-button border-rose-200 text-rose-700 hover:bg-rose-50" disabled={save.isPending || removeFeedback.isPending} onClick={() => setConfirmRemoval(true)} type="button">Remover feedback manual</button>}
    </section>
  );
}

function SessionEvaluationSummary({ evaluation }: { evaluation: SwimActivityDetailV2["session_evaluation"] }) {
  const garmin = evaluationParts(evaluation.garmin);
  const effective = evaluationParts(evaluation.effective, evaluation.provenance);
  return (
    <div className="session-evaluation">
      <div><p className="text-xs font-bold uppercase tracking-wider text-cyan-800">Garmin FIT</p><p className="mt-1 font-semibold text-slate-900">{garmin.length ? `Importado do Garmin: ${garmin.join(" · ")}` : "Esta atividade não trouxe esforço ou sensação."}</p></div>
      {effective.length > 0 && <div><p className="text-xs font-bold uppercase tracking-wider text-slate-500">Valores em uso</p><p className="mt-1 text-sm text-slate-700">{effective.join(" · ")}</p></div>}
      <p className="text-xs leading-5 text-slate-500">Esforço e sensação podem vir do relógio. Técnica, dor e notas continuam manuais.</p>
    </div>
  );
}

function ChoiceRow({ label, values, selected, onSelect, suffix }: { label: string; values: number[]; selected: number | null; onSelect: (value: number) => void; suffix: string }) { return <fieldset><legend className="mb-3 text-sm font-semibold text-slate-700">{label} <span className="font-normal text-slate-400">{selected === null ? "não informado" : `${selected}${suffix}`}</span></legend><div className="choice-row">{values.map((value) => <button aria-pressed={selected === value} className={selected === value ? "selected" : ""} key={value} onClick={() => onSelect(value)} type="button">{value}</button>)}</div></fieldset>; }
function HeroMetric({ label, value }: { label: string; value: string }) { return <div><p className="text-xs text-cyan-200">{label}</p><p className="mt-1 font-mono text-sm font-bold">{value}</p></div>; }
function Metric({ icon: Icon, label, value, detail }: { icon: typeof Gauge; label: string; value: string; detail: string }) { return <article className="analysis-metric"><Icon className="size-5 text-cyan-700" /><div><p className="font-mono text-xl font-bold tracking-tight">{value}</p><p className="text-xs font-semibold text-slate-600">{label}</p><p className="mt-1 text-[11px] text-slate-400">{detail}</p></div></article>; }
function Page({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) { return <div className="page-stack"><section><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1></section>{children}</div>; }
function formatDate(value: string, timezone: string) { return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short", timeZone: timezone }).format(new Date(value)); }
function formatDuration(value: unknown) { if (value === null || value === undefined || value === "") return "—"; const seconds = Number(value); if (!Number.isFinite(seconds)) return "—"; const rounded = Math.round(seconds); const minutes = Math.floor(rounded / 60); const rest = rounded % 60; return minutes ? `${minutes}min ${rest}s` : `${rest}s`; }
function formatPace(value: unknown) { const seconds = Number(value); if (!Number.isFinite(seconds) || seconds <= 0) return "—"; const rounded = Math.round(seconds); return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}/100m`; }
function formatPercent(value: unknown) { const number = Number(value); return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "—"; }
function formatSignedPercent(value: unknown) { const number = Number(value); return Number.isFinite(number) ? `${number > 0 ? "+" : ""}${number.toFixed(1)}%` : "—"; }
function formatNumber(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number.toFixed(1) : "—"; }
function nullableNumber(value: unknown) { if (value === null || value === undefined || value === "") return null; const number = Number(value); return Number.isFinite(number) ? number : null; }
function manualRpeDefault(value: unknown) { const number = nullableNumber(value); return number === null ? 5 : Math.min(10, Math.max(1, Math.round(number))); }
function formatRpe(value: unknown) { const number = nullableNumber(value); return number === null ? "—" : number.toLocaleString("pt-BR", { maximumFractionDigits: 1 }); }
function evaluationParts(
  values: SwimActivityDetailV2["session_evaluation"]["garmin"],
  provenance?: SwimActivityDetailV2["session_evaluation"]["provenance"],
) {
  const result: string[] = [];
  if (values.rpe !== null) result.push(`RPE ${formatRpe(values.rpe)}/10${evaluationSourceSuffix(provenance?.rpe.source)}`);
  if (values.feeling_score !== null) result.push(`sensação ${values.feeling_score}/100${evaluationSourceSuffix(provenance?.feeling_score.source)}`);
  return result;
}
function evaluationSourceSuffix(source: "MANUAL_OVERRIDE" | "GARMIN" | null | undefined) { return source === "MANUAL_OVERRIDE" ? " (ajuste manual)" : source === "GARMIN" ? " (Garmin)" : ""; }
function importedEvaluationNotice(hasRpe: boolean, hasFeeling: boolean) { const imported = hasRpe && hasFeeling ? "Esforço e sensação já foram importados" : hasRpe ? "O esforço já foi importado" : "A sensação já foi importada"; return `${imported} do Garmin. Salve apenas se quiser acrescentar ou ajustar algo.`; }
function feedbackFormStateKey(detail: SwimActivityDetailV2) { const evaluation = detail.session_evaluation; return JSON.stringify([detail.activity_id, evaluation.garmin.rpe, evaluation.garmin.feeling_score, evaluation.manual_override.rpe, evaluation.manual_override.feeling_score, evaluation.provenance.rpe.source, evaluation.provenance.feeling_score.source, detail.feedback?.id ?? null, detail.feedback?.version ?? null]); }
function poolLabel(value: number | null) { return value === null ? "piscina desconhecida" : `piscina de ${value} m`; }
function qualityLabel(value: SwimActivityDetailV2["data_quality"]["level"]) { return ({ HIGH: "alta", MEDIUM: "parcial", LOW: "limitada" } as Record<string, string>)[value] ?? "pendente"; }
function warningLabel(value: string) { return ({ SESSION_LENGTH_DISTANCE_MISMATCH: "distância da sessão divergiu das extensões", LENGTH_MESSAGES_UNAVAILABLE: "extensões ausentes", LAP_MESSAGES_SYNTHESIZED: "série reconstruída do resumo", PACE_SERIES_UNAVAILABLE: "ritmo por série ausente", CONSISTENCY_SAMPLE_INSUFFICIENT: "amostra curta para consistência", FADE_SAMPLE_INSUFFICIENT: "amostra curta para fade", SWOLF_UNAVAILABLE: "SWOLF ausente" } as Record<string, string>)[value] ?? value.toLocaleLowerCase().replaceAll("_", " "); }
function strokeLabel(value: string | null) { return ({ freestyle: "livre", backstroke: "costas", breaststroke: "peito", butterfly: "borboleta", drill: "educativo", mixed: "misto" } as Record<string, string>)[value ?? ""] ?? "nado"; }
function intervalIsRest(interval: SwimActivityDetailV2["intervals"][number]) { return interval.interval_type === "REST" || interval.planned_role === "REST"; }
function intervalIsDrill(interval: SwimActivityDetailV2["intervals"][number]) { return interval.interval_type === "DRILL" || interval.planned_role === "DRILL"; }
function intervalTitle(interval: SwimActivityDetailV2["intervals"][number]) { if (intervalIsRest(interval)) return interval.interval_type === "REST" ? "Descanso" : "Descanso planejado · tipo detectado incerto"; const kind = intervalIsDrill(interval) ? "educativo" : strokeLabel(interval.detected_stroke); return `${interval.distance_m} m · ${kind}`; }
function intervalDetail(interval: SwimActivityDetailV2["intervals"][number]) { if (intervalIsRest(interval)) { const label = interval.interval_type === "REST" ? "descanso explícito" : "descanso contextual do planejamento"; const explicitRest = Number(interval.durations.rest_s); const restDuration = Number.isFinite(explicitRest) && explicitRest > 0 ? interval.durations.rest_s : interval.planned_role === "REST" ? interval.durations.timer_s : interval.durations.rest_s; return `${formatDuration(restDuration)} ${label} · ${formatDuration(interval.durations.timer_s)} timer`; } return `${formatDuration(interval.durations.swim_s)} extensões ativas · ${formatDuration(interval.durations.moving_s)} moving · ${formatDuration(interval.durations.timer_s)} timer`; }
function intervalPace(interval: SwimActivityDetailV2["intervals"][number]) { if (intervalIsRest(interval)) return "—"; if (interval.paces.moving_s_per_100m !== null) return `${formatPace(interval.paces.moving_s_per_100m)} · moving`; if (interval.paces.swim_s_per_100m !== null) return `${formatPace(interval.paces.swim_s_per_100m)} · extensões`; return "—"; }
function firstStrokeEfficiency(metrics: Record<string, unknown> | undefined) { const groups = metrics?.stroke_efficiency; if (!Array.isArray(groups)) return undefined; const records = groups.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null); return records.find((item) => item.stroke === "freestyle" && item.planned_role === "WORK") ?? records.find((item) => item.stroke === "freestyle") ?? records[0]; }
function firstFreestyleWorkSet(metrics: Record<string, unknown> | undefined) { const sets = metrics?.sets; if (!Array.isArray(sets)) return undefined; const records = sets.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null); return records.find((item) => { const key = item.key; return typeof key === "object" && key !== null && (key as Record<string, unknown>).stroke === "FREESTYLE" && (key as Record<string, unknown>).planned_role === "WORK"; }); }
function analysisDuration(metrics: Record<string, unknown> | undefined, key: string) { const durations = metrics?.durations; if (typeof durations !== "object" || durations === null) return undefined; const value = (durations as Record<string, unknown>)[key]; return typeof value === "string" || typeof value === "number" ? value : value === null ? null : undefined; }
