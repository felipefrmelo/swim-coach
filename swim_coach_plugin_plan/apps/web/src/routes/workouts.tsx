import { useId, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CalendarCheck,
  CheckCircle2,
  ChevronRight,
  Plus,
  Repeat2,
  Save,
  Send,
  TimerReset,
  Trash2,
  Waves,
} from "lucide-react";

import { api } from "../api/client";
import type {
  CanonicalWorkout,
  Workout,
  WorkoutNode,
  WorkoutPurpose,
  WorkoutRepeat,
  WorkoutRole,
  WorkoutStep,
} from "../api/types";
import { ErrorState, LoadingState, SavedNotice } from "../components/AsyncState";
import { formatPace, parsePace } from "./workout-pace";

const purposeLabels: Record<WorkoutPurpose, string> = {
  TECHNIQUE: "Técnica", BASE: "Base", ENDURANCE: "Endurance", THRESHOLD: "Limiar",
  SPEED: "Velocidade", RECOVERY: "Recuperação", TEST: "Teste", MIXED: "Misto",
};

const statusLabels: Record<Workout["status"], string> = {
  draft: "Rascunho", approved: "Salvo", scheduled: "Agendado",
  published: "Publicado", completed: "Concluído", cancelled: "Cancelado", archived: "Arquivado",
};

const garminWarningMessages: Record<string, string> = {
  RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY: "A Garmin aceita uma categoria de esforço por etapa. A faixa de RPE será convertida e também ficará nas notas.",
  RPE_TARGET_DOWNGRADED_TO_TEXT: "A faixa de RPE ficará nas notas porque a meta de esforço nativa não está disponível.",
  PACE_TARGET_DOWNGRADED_TO_TEXT: "O ritmo desejado ficará nas notas porque a meta de ritmo nativa não está disponível.",
  ZONE_TARGET_DOWNGRADED_TO_TEXT: "A zona existente ficará nas notas porque esse alvo nativo ainda não é suportado.",
  DRILL_STROKE_DOWNGRADED_TO_CHOICE: "O Garmin receberá este educativo com o estilo genérico Livre escolha.",
  EQUIPMENT_OMITTED_FROM_GARMIN_PAYLOAD: "O equipamento desta etapa não será enviado ao Garmin.",
};

function starterWorkout(poolLength = 20): CanonicalWorkout {
  return {
    schema_version: "1.0",
    title: "Técnica + endurance — 1.600 m",
    sport: "POOL_SWIMMING",
    pool_length_m: poolLength,
    purpose: "ENDURANCE",
    tags: ["20m", "endurance"],
    nodes: [
      distanceStep("warmup", "WARMUP", 200),
      {
        type: "repeat", id: "main", label: "Série principal", repetitions: 6,
        children: [distanceStep(undefined, "WORK", 200), restStep(20)],
      },
      distanceStep("cooldown", "COOLDOWN", 200),
    ],
  };
}

function distanceStep(id: string | undefined, role: WorkoutRole, meters: number): WorkoutStep {
  return {
    type: "step", id, step_role: role,
    end_condition: { type: "distance", meters },
    target: { type: "none" }, stroke: { type: "freestyle" },
    intensity: role === "WARMUP" || role === "COOLDOWN" ? "EASY" : "MODERATE",
  };
}

function restStep(seconds: number): WorkoutStep {
  return { type: "step", step_role: "REST", end_condition: { type: "time", seconds }, target: { type: "none" }, stroke: { type: "freestyle" } };
}

function calculate(nodes: WorkoutNode[], poolLength: number) {
  let distance = 0; let steps = 0; let restSeconds = 0;
  const errors: string[] = [];
  const garminWarningCodes = new Set<string>();
  function walk(items: WorkoutNode[], multiplier: number, depth: number) {
    if (depth > 4) errors.push("Use no máximo quatro níveis de repetição.");
    items.forEach((node) => {
      if (node.type === "repeat") { walk(node.children, multiplier * node.repetitions, depth + 1); return; }
      steps += multiplier;
      if (node.target?.type === "rpe") garminWarningCodes.add("RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY");
      if (node.target?.type === "zone") garminWarningCodes.add("ZONE_TARGET_DOWNGRADED_TO_TEXT");
      if (node.target?.type === "rpe" && (!Number.isInteger(node.target.min) || !Number.isInteger(node.target.max) || node.target.min < 1 || node.target.max > 10)) errors.push("Use valores inteiros de RPE entre 1 e 10.");
      if (node.target?.type === "rpe" && node.target.min > node.target.max) errors.push("O RPE mínimo não pode ser maior que o máximo.");
      if (node.target?.type === "pace_range" && (!Number.isFinite(node.target.min_seconds_per_100m) || !Number.isFinite(node.target.max_seconds_per_100m))) errors.push("Use o formato mm:ss nos dois limites de ritmo.");
      if (node.target?.type === "pace_range" && node.target.min_seconds_per_100m > node.target.max_seconds_per_100m) errors.push("O ritmo mais rápido deve ser menor ou igual ao ritmo mais lento.");
      if (node.end_condition.type === "distance") {
        distance += node.end_condition.meters * multiplier;
        if (node.end_condition.meters % poolLength) errors.push(`${node.end_condition.meters} m não termina na parede de ${poolLength} m.`);
      } else if (node.end_condition.type === "time" && node.step_role === "REST") {
        restSeconds += node.end_condition.seconds * multiplier;
      }
    });
  }
  walk(nodes, 1, 1);
  return { distance, steps, restSeconds, errors: [...new Set(errors)], garminWarningCodes };
}

export function WorkoutsPage() {
  const workouts = useQuery({ queryKey: ["workouts"], queryFn: api.workouts });
  if (workouts.isLoading) return <LoadingState label="Carregando treinos…" />;
  if (!workouts.data) return <ErrorState message="Não foi possível carregar os treinos." />;
  return (
    <Page title="Treinos" eyebrow="Editor canônico · piscina de 20 m">
      <Link className="primary-button w-full gap-2 sm:w-fit" to="/workouts/new"><Plus className="size-4" />Criar treino</Link>
      {workouts.data.length ? <div className="grid gap-3">{workouts.data.map((workout) => (
        <Link className="surface-card workout-list-row" key={workout.id} to="/workouts/$workoutId" params={{ workoutId: workout.id }}>
          <div><span className="badge">{statusLabels[workout.status]}</span><h2 className="section-title mt-3">{workout.title}</h2><p className="mt-1 text-sm text-slate-500">{purposeLabels[workout.purpose]} · revisão {workout.current_revision.revision_number}</p></div>
          <div className="flex items-center gap-3"><p className="font-bold tabular-nums text-cyan-950">{workout.current_revision.validation.totals.distance_m.toLocaleString("pt-BR")} m</p><ChevronRight className="size-5 text-slate-400" /></div>
        </Link>
      ))}</div> : <section className="empty-card"><Waves className="size-7 text-cyan-800" /><div><h2 className="section-title">Sua biblioteca está vazia</h2><p className="mt-2 text-sm leading-6 text-slate-600">Comece pelo preset de 1.600 m. Os totais e a parede são validados ao vivo.</p></div></section>}
    </Page>
  );
}

export function NewWorkoutPage() {
  const pools = useQuery({ queryKey: ["pools"], queryFn: api.pools });
  if (pools.isLoading) return <LoadingState label="Preparando o editor…" />;
  const pool = pools.data?.find((item) => item.is_default) ?? pools.data?.[0];
  if (!pool) return <ErrorState message="Configure uma piscina antes de criar um treino." />;
  return <WorkoutEditor poolId={pool.id} initial={starterWorkout(pool.length_m)} />;
}

export function WorkoutDetailPage() {
  const { workoutId } = useParams({ strict: false }) as { workoutId: string };
  const workout = useQuery({ queryKey: ["workout", workoutId], queryFn: () => api.workout(workoutId) });
  if (workout.isLoading) return <LoadingState label="Carregando revisão…" />;
  if (!workout.data) return <ErrorState message="O treino não foi encontrado." />;
  return <WorkoutEditor poolId={workout.data.pool_id} initial={workout.data.current_revision.definition} existing={workout.data} />;
}

function WorkoutEditor({ poolId, initial, existing }: { poolId: string; initial: CanonicalWorkout; existing?: Workout }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [definition, setDefinition] = useState<CanonicalWorkout>(() => structuredClone(initial));
  const [nodeKeys, setNodeKeys] = useState(() => initial.nodes.map((node) => node.id ?? crypto.randomUUID()));
  const [changeReason, setChangeReason] = useState("");
  const [scheduleDate, setScheduleDate] = useState(existing?.schedule?.scheduled_date ?? new Date().toISOString().slice(0, 10));
  const [scheduleTime, setScheduleTime] = useState(existing?.schedule?.scheduled_start_time?.slice(0, 5) ?? "19:00");
  const totals = useMemo(() => calculate(definition.nodes, definition.pool_length_m), [definition]);
  const save = useMutation({
    mutationFn: (publishToGarmin: boolean) => api.saveWorkout({
      workout_id: existing?.id ?? null,
      pool_id: poolId,
      definition,
      scheduled_date: scheduleDate || null,
      scheduled_start_time: scheduleTime ? `${scheduleTime}:00` : null,
      change_reason: changeReason || null,
      publish_to_garmin: publishToGarmin,
    }),
    onSuccess: async (saved) => {
      queryClient.setQueryData(["workout", saved.workout.id], saved.workout);
      await queryClient.invalidateQueries({ queryKey: ["workouts"] });
      await navigate({ to: "/workouts/$workoutId", params: { workoutId: saved.workout.id } });
    },
  });
  const garminAdvisories = useMemo(() => {
    const codes = new Set(totals.garminWarningCodes);
    for (const code of save.data?.garmin?.warnings ?? []) codes.add(code);
    return [...codes].map(garminWarningMessage);
  }, [totals.garminWarningCodes, save.data]);
  const remove = useMutation({
    mutationFn: () => api.deleteWorkout(existing!.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ["workout", existing!.id] });
      await queryClient.invalidateQueries({ queryKey: ["workouts"] });
      await navigate({ to: "/workouts" });
    },
  });

  function updateNode(index: number, node: WorkoutNode) { setDefinition((value) => ({ ...value, nodes: value.nodes.map((item, itemIndex) => itemIndex === index ? node : item) })); }
  function moveNode(index: number, direction: -1 | 1) { setDefinition((value) => { const nodes = [...value.nodes]; const target = index + direction; if (target < 0 || target >= nodes.length) return value; [nodes[index], nodes[target]] = [nodes[target], nodes[index]]; return { ...value, nodes }; }); setNodeKeys((value) => { const keys = [...value]; const target = index + direction; if (target < 0 || target >= keys.length) return value; [keys[index], keys[target]] = [keys[target], keys[index]]; return keys; }); }
  function removeNode(index: number) { setDefinition((value) => ({ ...value, nodes: value.nodes.filter((_, itemIndex) => itemIndex !== index) })); setNodeKeys((value) => value.filter((_, itemIndex) => itemIndex !== index)); }
  function addStep() { setDefinition((value) => ({ ...value, nodes: [...value.nodes, distanceStep(undefined, "WORK", value.pool_length_m * 2)] })); setNodeKeys((value) => [...value, crypto.randomUUID()]); }
  function addRepeat() { const repeat: WorkoutRepeat = { type: "repeat", repetitions: 4, children: [distanceStep(undefined, "WORK", definition.pool_length_m * 4), restStep(20)] }; setDefinition((value) => ({ ...value, nodes: [...value.nodes, repeat] })); setNodeKeys((value) => [...value, crypto.randomUUID()]); }

  return (
    <Page title={existing ? "Editar treino" : "Novo treino"} eyebrow={`Modelo canônico · ${definition.pool_length_m} m`}>
      <section className="workout-totals" aria-live="polite"><div><p className="eyebrow text-cyan-200">Total ao vivo</p><p className="text-4xl font-bold tracking-tight tabular-nums">{totals.distance.toLocaleString("pt-BR")} m</p></div><div className="text-right text-sm text-cyan-100"><p>{totals.steps} etapas executáveis</p><p>{totals.restSeconds} s de descanso</p></div></section>
      <section className="surface-card form-stack">
        <Field label="Nome do treino"><input value={definition.title} maxLength={160} onChange={(event) => setDefinition({ ...definition, title: event.target.value })} /></Field>
        <Field label="Objetivo"><select value={definition.purpose} onChange={(event) => setDefinition({ ...definition, purpose: event.target.value as WorkoutPurpose })}>{Object.entries(purposeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      </section>
      <section aria-labelledby="structure-title"><div className="mb-4 flex items-center justify-between gap-3"><div><p className="eyebrow">Estrutura</p><h2 id="structure-title" className="section-title mt-1">Blocos do treino</h2></div><span className="badge">termina na parede</span></div><div className="grid gap-3">{definition.nodes.map((node, index) => <NodeEditor key={nodeKeys[index]} node={node} position={index + 1} poolLength={definition.pool_length_m} onChange={(next) => updateNode(index, next)} onMove={(direction) => moveNode(index, direction)} onRemove={() => removeNode(index)} first={index === 0} last={index === definition.nodes.length - 1} />)}</div><div className="mt-4 grid grid-cols-2 gap-3"><button className="secondary-button gap-2" type="button" onClick={addStep}><Plus className="size-4" />Etapa</button><button className="secondary-button gap-2" type="button" onClick={addRepeat}><Repeat2 className="size-4" />Repetição</button></div></section>
      <ValidationPanel errors={totals.errors} />
      {garminAdvisories.length > 0 && <section className="setup-notice" role="status" aria-live="polite"><AlertTriangle className="size-5 flex-none" aria-hidden="true" /><div><h2 className="font-bold">Como a meta irá para o Garmin</h2>{garminAdvisories.map((message) => <p className="mt-1" key={message}>{message}</p>)}</div></section>}
      {existing && <Field label="Motivo da nova revisão"><input value={changeReason} maxLength={500} onChange={(event) => setChangeReason(event.target.value)} placeholder="Ex.: ajustar volume da série principal" /></Field>}
      <section className="surface-card form-stack"><div><p className="eyebrow">Agenda</p><h2 className="section-title mt-1">Quando nadar</h2></div><div className="grid grid-cols-2 gap-3"><Field label="Data"><input type="date" value={scheduleDate} onChange={(event) => setScheduleDate(event.target.value)} /></Field><Field label="Horário"><input type="time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} /></Field></div></section>
      {existing && <section className="surface-card"><h2 className="section-title">Histórico</h2><p className="mt-2 text-sm text-slate-600">{existing.revisions.length} revisões preservadas automaticamente.</p></section>}
      {save.isError && <ErrorState message="Não foi possível salvar o treino." />}
      {remove.isError && <ErrorState message="Não foi possível excluir o treino." />}
      {save.isSuccess && <SavedNotice>{save.data.garmin ? "Treino salvo e envio ao Garmin iniciado." : "Treino salvo e agendado."}</SavedNotice>}
      <div className="grid gap-3 sm:grid-cols-2"><button className="secondary-button gap-2" type="button" disabled={save.isPending || !definition.title || definition.nodes.length === 0 || totals.errors.length > 0} onClick={() => save.mutate(false)}><Save className="size-4" />{save.isPending ? "Salvando…" : "Salvar"}</button><button className="primary-button gap-2" type="button" disabled={save.isPending || !scheduleDate || !definition.title || definition.nodes.length === 0 || totals.errors.length > 0} onClick={() => save.mutate(true)}><Send className="size-4" />{save.isPending ? "Enviando…" : "Salvar e enviar ao Garmin"}</button></div>
      {existing && existing.status !== "completed" && <button className="secondary-button gap-2 border-red-300 text-red-900" type="button" disabled={remove.isPending} onClick={() => window.confirm("Excluir este treino da agenda, do Swim Coach e do Garmin?") && remove.mutate()}><Trash2 className="size-4" />{remove.isPending ? "Excluindo…" : "Excluir treino"}</button>}
    </Page>
  );
}

function NodeEditor({ node, position, poolLength, onChange, onMove, onRemove, first, last }: { node: WorkoutNode; position: number; poolLength: number; onChange: (node: WorkoutNode) => void; onMove: (direction: -1 | 1) => void; onRemove: () => void; first: boolean; last: boolean }) {
  const accessibleName = node.type === "repeat" ? `Bloco ${position}: grupo de repetição` : `Etapa ${position}: ${roleLabel(node.step_role ?? "WORK")}`;
  return <article className="workout-node" aria-label={accessibleName}><div className="flex items-center gap-3"><span className="icon-chip">{node.type === "repeat" ? <Repeat2 className="size-5" /> : <Waves className="size-5" />}</span><div className="min-w-0 flex-1"><p className="font-semibold">{node.type === "repeat" ? "Grupo de repetição" : roleLabel(node.step_role ?? "WORK")}</p><p className="text-xs text-slate-500">{node.type === "repeat" ? `${node.repetitions} voltas` : `${endLabel(node)} · ${targetLabel(node.target)}`}</p></div><div className="flex"><IconButton label="Mover para cima" disabled={first} onClick={() => onMove(-1)}><ArrowUp /></IconButton><IconButton label="Mover para baixo" disabled={last} onClick={() => onMove(1)}><ArrowDown /></IconButton><IconButton label="Remover bloco" onClick={onRemove}><Trash2 /></IconButton></div></div>{node.type === "repeat" ? <RepeatFields node={node} poolLength={poolLength} onChange={onChange} /> : <StepFields node={node} poolLength={poolLength} onChange={onChange} />}</article>;
}

function StepFields({ node, poolLength, onChange }: { node: WorkoutStep; poolLength: number; onChange: (node: WorkoutStep) => void }) {
  const isDistance = node.end_condition.type === "distance";
  const target = node.target ?? { type: "none" as const };
  const isRest = node.step_role === "REST";
  return <div className="mt-4 grid gap-3">
    <div className="grid grid-cols-2 gap-3"><Field label="Tipo"><select value={node.step_role ?? "WORK"} onChange={(event) => { const role = event.target.value as WorkoutRole; onChange({ ...node, step_role: role, end_condition: role === "REST" ? { type: "time", seconds: 20 } : isDistance ? node.end_condition : { type: "distance", meters: poolLength * 2 }, target: role === "REST" ? { type: "none" } : target }); }}>{["WARMUP", "WORK", "DRILL", "RECOVERY", "REST", "COOLDOWN"].map((role) => <option key={role} value={role}>{roleLabel(role as WorkoutRole)}</option>)}</select></Field><Field label={isRest ? "Segundos" : "Distância (m)"}><input type="number" min={isRest ? 1 : poolLength} step={isRest ? 1 : poolLength} value={node.end_condition.type === "distance" ? node.end_condition.meters : node.end_condition.type === "time" ? node.end_condition.seconds : 1} onChange={(event) => onChange({ ...node, end_condition: isRest ? { type: "time", seconds: Number(event.target.value) } : { type: "distance", meters: Number(event.target.value) } })} /></Field></div>
    {!isRest && <>
      <Field label="Tipo de meta"><select aria-label="Tipo de meta" value={target.type} onChange={(event) => onChange({ ...node, target: newTarget(event.target.value) })}><option value="none">Sem objetivo</option><option value="rpe">Baseado no esforço (RPE)</option><option value="pace_range">Ritmo desejado</option>{target.type === "zone" && <option value="zone" disabled>Zona atual: {target.zone}</option>}</select></Field>
      {target.type === "rpe" && <div className="grid grid-cols-2 gap-3"><Field label="RPE mínimo"><input aria-label="RPE mínimo" aria-invalid={!Number.isInteger(target.min) || target.min < 1 || target.min > 10 || target.min > target.max} type="number" min="1" max="10" value={target.min} onChange={(event) => onChange({ ...node, target: { ...target, min: Number(event.target.value) } })} /></Field><Field label="RPE máximo"><input aria-label="RPE máximo" aria-invalid={!Number.isInteger(target.max) || target.max < 1 || target.max > 10 || target.min > target.max} type="number" min="1" max="10" value={target.max} onChange={(event) => onChange({ ...node, target: { ...target, max: Number(event.target.value) } })} /></Field></div>}
      {target.type === "pace_range" && <div className="grid grid-cols-2 gap-3"><PaceField label="Mais rápido (/100 m)" seconds={target.min_seconds_per_100m} onChange={(seconds) => onChange({ ...node, target: { ...target, min_seconds_per_100m: seconds } })} /><PaceField label="Mais lento (/100 m)" seconds={target.max_seconds_per_100m} onChange={(seconds) => onChange({ ...node, target: { ...target, max_seconds_per_100m: seconds } })} /></div>}
    </>}
    <Field label="Notas"><textarea aria-label="Notas" maxLength={600} rows={3} value={node.instructions ?? ""} onChange={(event) => onChange({ ...node, instructions: event.target.value || null })} placeholder="Técnica, respiração ou orientação para esta etapa…" /></Field>
  </div>;
}

function newTarget(type: string): NonNullable<WorkoutStep["target"]> {
  if (type === "rpe") return { type: "rpe", min: 3, max: 4 };
  if (type === "pace_range") return { type: "pace_range", min_seconds_per_100m: 135, max_seconds_per_100m: 150 };
  return { type: "none" };
}

function PaceField({ label, seconds, onChange }: { label: string; seconds: number; onChange: (seconds: number) => void }) {
  const errorId = useId();
  const [draft, setDraft] = useState(() => formatPace(seconds));
  const invalid = parsePace(draft) === null;
  return <Field label={label}><input aria-label={label} aria-invalid={invalid} aria-describedby={invalid ? errorId : undefined} type="text" inputMode="numeric" pattern="[0-9]+:[0-5][0-9]" value={draft} onChange={(event) => setDraft(event.currentTarget.value)} onBlur={() => onChange(parsePace(draft) ?? Number.NaN)} />{invalid && <span id={errorId} role="alert" className="text-xs font-medium text-rose-700">Use minutos e segundos, por exemplo 2:15.</span>}</Field>;
}

function RepeatFields({ node, poolLength, onChange }: { node: WorkoutRepeat; poolLength: number; onChange: (node: WorkoutRepeat) => void }) {
  return <div className="mt-4 grid gap-3"><Field label="Repetições"><input type="number" min="1" max="100" value={node.repetitions} onChange={(event) => onChange({ ...node, repetitions: Number(event.target.value) })} /></Field><div className="repeat-children">{node.children.map((child, index) => <section className="rounded-xl bg-white p-3" aria-label={child.type === "step" ? `Etapa ${index + 1} do grupo` : `Grupo aninhado ${index + 1}`} key={`${child.id ?? child.type}-${index}`}><p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">{child.type === "step" ? `Etapa ${index + 1}` : `Grupo ${index + 1}`}</p>{child.type === "step" ? <StepFields node={child} poolLength={poolLength} onChange={(next) => onChange({ ...node, children: node.children.map((item, itemIndex) => itemIndex === index ? next : item) })} /> : <RepeatFields node={child} poolLength={poolLength} onChange={(next) => onChange({ ...node, children: node.children.map((item, itemIndex) => itemIndex === index ? next : item) })} />}</section>)}</div></div>;
}

function ValidationPanel({ errors }: { errors: string[] }) { return errors.length ? <section className="validation-panel validation-error" role="alert" aria-live="assertive"><AlertTriangle className="size-5" /><div><h2 className="font-bold">Ajuste estes blocos</h2>{errors.map((error) => <p className="mt-1 text-sm" key={error}>{error}</p>)}</div></section> : <section className="validation-panel" role="status"><CheckCircle2 className="size-5" /><div><h2 className="font-bold">Pronto para salvar</h2><p className="mt-1 text-sm">Todas as distâncias terminam na parede.</p></div></section>; }
function garminWarningMessage(code: string) { return garminWarningMessages[code] ?? "O Garmin ajustará parte desta etapa durante o envio."; }
function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactElement }) { return <button className="icon-button" type="button" aria-label={label} disabled={disabled} onClick={onClick}>{children}</button>; }
function roleLabel(role: WorkoutRole) { return ({ WARMUP: "Aquecimento", WORK: "Nado", RECOVERY: "Recuperação", REST: "Descanso", COOLDOWN: "Soltura", DRILL: "Educativo", OTHER: "Outro" } as Record<WorkoutRole, string>)[role]; }
function endLabel(node: WorkoutStep) { return node.end_condition.type === "distance" ? `${node.end_condition.meters} m` : node.end_condition.type === "time" ? `${node.end_condition.seconds} s` : "Botão lap"; }
function targetLabel(target: WorkoutStep["target"]) {
  if (!target) return "sem objetivo";
  switch (target.type) {
    case "none": return "sem objetivo";
    case "rpe": return `RPE ${target.min}–${target.max}`;
    case "pace_range": return Number.isFinite(target.min_seconds_per_100m) && Number.isFinite(target.max_seconds_per_100m) ? `${formatPace(target.min_seconds_per_100m)}–${formatPace(target.max_seconds_per_100m)}/100 m` : "ritmo inválido";
    case "zone": return target.zone;
  }
}
function Page({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) { return <div className="page-stack"><section><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1></section>{children}</div>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="grid gap-2 text-sm font-semibold text-slate-700"><span>{label}</span>{children}</label>; }

export function CalendarPage() {
  const workouts = useQuery({ queryKey: ["workouts"], queryFn: api.workouts });
  const [view, setView] = useState<"week" | "month">("week");
  if (workouts.isLoading) return <LoadingState label="Montando calendário…" />;
  if (!workouts.data) return <ErrorState message="Não foi possível carregar o calendário." />;
  const scheduled = workouts.data.filter((item) => item.schedule).sort((a, b) => a.schedule!.scheduled_date.localeCompare(b.schedule!.scheduled_date));
  return <Page title="Calendário" eyebrow="Agenda local · America/Sao_Paulo"><div className="segmented-control" aria-label="Visualização"><button className={view === "week" ? "active" : ""} onClick={() => setView("week")} type="button">Semana</button><button className={view === "month" ? "active" : ""} onClick={() => setView("month")} type="button">Mês</button></div>{scheduled.length ? <div className="grid gap-3">{scheduled.map((workout) => <Link className="surface-card workout-list-row" key={workout.id} to="/workouts/$workoutId" params={{ workoutId: workout.id }}><div><p className="eyebrow">{new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: view === "month" ? "long" : "short", timeZone: workout.schedule!.timezone }).format(new Date(`${workout.schedule!.scheduled_date}T12:00:00`))}</p><h2 className="section-title mt-2">{workout.title}</h2><p className="mt-1 text-sm text-slate-500">{workout.schedule!.scheduled_start_time?.slice(0, 5) ?? "Horário livre"} · {workout.current_revision.validation.totals.distance_m.toLocaleString("pt-BR")} m</p></div><TimerReset className="size-5 text-cyan-800" /></Link>)}</div> : <section className="empty-card"><CalendarCheck className="size-7 text-cyan-800" /><div><h2 className="section-title">Nenhum treino agendado</h2><p className="mt-2 text-sm text-slate-600">Crie um treino e escolha a data; o salvamento cuida do restante.</p></div></section>}</Page>;
}
