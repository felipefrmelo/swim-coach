import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CalendarCheck,
  CheckCircle2,
  ChevronRight,
  CopyPlus,
  Plus,
  Repeat2,
  Save,
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

const purposeLabels: Record<WorkoutPurpose, string> = {
  TECHNIQUE: "Técnica", BASE: "Base", ENDURANCE: "Endurance", THRESHOLD: "Limiar",
  SPEED: "Velocidade", RECOVERY: "Recuperação", TEST: "Teste", MIXED: "Misto",
};

const statusLabels: Record<Workout["status"], string> = {
  draft: "Rascunho", approved: "Aprovado localmente", scheduled: "Agendado",
  cancelled: "Cancelado", archived: "Arquivado",
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
  function walk(items: WorkoutNode[], multiplier: number, depth: number) {
    if (depth > 4) errors.push("Use no máximo quatro níveis de repetição.");
    items.forEach((node) => {
      if (node.type === "repeat") { walk(node.children, multiplier * node.repetitions, depth + 1); return; }
      steps += multiplier;
      if (node.end_condition.type === "distance") {
        distance += node.end_condition.meters * multiplier;
        if (node.end_condition.meters % poolLength) errors.push(`${node.end_condition.meters} m não termina na parede de ${poolLength} m.`);
      } else if (node.end_condition.type === "time" && node.step_role === "REST") {
        restSeconds += node.end_condition.seconds * multiplier;
      }
    });
  }
  walk(nodes, 1, 1);
  return { distance, steps, restSeconds, errors: [...new Set(errors)] };
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
  const [changeReason, setChangeReason] = useState("");
  const [scheduleDate, setScheduleDate] = useState(existing?.schedule?.scheduled_date ?? new Date().toISOString().slice(0, 10));
  const [scheduleTime, setScheduleTime] = useState(existing?.schedule?.scheduled_start_time?.slice(0, 5) ?? "19:00");
  const totals = useMemo(() => calculate(definition.nodes, definition.pool_length_m), [definition]);
  const save = useMutation({
    mutationFn: () => existing ? api.reviseWorkout(existing, definition, changeReason) : api.createWorkout(poolId, definition),
    onSuccess: async (saved) => {
      queryClient.setQueryData(["workout", saved.id], saved);
      await queryClient.invalidateQueries({ queryKey: ["workouts"] });
      await navigate({ to: "/workouts/$workoutId", params: { workoutId: saved.id } });
    },
  });
  const approve = useMutation({ mutationFn: () => api.approveWorkout(existing!), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["workout", existing?.id] }) });
  const schedule = useMutation({ mutationFn: () => api.scheduleWorkout(existing!, scheduleDate, scheduleTime ? `${scheduleTime}:00` : null, "America/Sao_Paulo"), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["workout", existing?.id] }); await queryClient.invalidateQueries({ queryKey: ["workouts"] }); } });

  function updateNode(index: number, node: WorkoutNode) { setDefinition((value) => ({ ...value, nodes: value.nodes.map((item, itemIndex) => itemIndex === index ? node : item) })); }
  function moveNode(index: number, direction: -1 | 1) { setDefinition((value) => { const nodes = [...value.nodes]; const target = index + direction; if (target < 0 || target >= nodes.length) return value; [nodes[index], nodes[target]] = [nodes[target], nodes[index]]; return { ...value, nodes }; }); }
  function removeNode(index: number) { setDefinition((value) => ({ ...value, nodes: value.nodes.filter((_, itemIndex) => itemIndex !== index) })); }
  function addStep() { setDefinition((value) => ({ ...value, nodes: [...value.nodes, distanceStep(undefined, "WORK", value.pool_length_m * 2)] })); }
  function addRepeat() { const repeat: WorkoutRepeat = { type: "repeat", repetitions: 4, children: [distanceStep(undefined, "WORK", definition.pool_length_m * 4), restStep(20)] }; setDefinition((value) => ({ ...value, nodes: [...value.nodes, repeat] })); }

  return (
    <Page title={existing ? "Editar treino" : "Novo treino"} eyebrow={`Modelo canônico · ${definition.pool_length_m} m`}>
      <section className="workout-totals" aria-live="polite"><div><p className="eyebrow text-cyan-200">Total ao vivo</p><p className="text-4xl font-bold tracking-tight tabular-nums">{totals.distance.toLocaleString("pt-BR")} m</p></div><div className="text-right text-sm text-cyan-100"><p>{totals.steps} etapas executáveis</p><p>{totals.restSeconds} s de descanso</p></div></section>
      <section className="surface-card form-stack">
        <Field label="Nome do treino"><input value={definition.title} maxLength={160} onChange={(event) => setDefinition({ ...definition, title: event.target.value })} /></Field>
        <Field label="Objetivo"><select value={definition.purpose} onChange={(event) => setDefinition({ ...definition, purpose: event.target.value as WorkoutPurpose })}>{Object.entries(purposeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      </section>
      <section aria-labelledby="structure-title"><div className="mb-4 flex items-center justify-between gap-3"><div><p className="eyebrow">Estrutura</p><h2 id="structure-title" className="section-title mt-1">Blocos do treino</h2></div><span className="badge">termina na parede</span></div><div className="grid gap-3">{definition.nodes.map((node, index) => <NodeEditor key={`${node.id ?? node.type}-${index}`} node={node} poolLength={definition.pool_length_m} onChange={(next) => updateNode(index, next)} onMove={(direction) => moveNode(index, direction)} onRemove={() => removeNode(index)} first={index === 0} last={index === definition.nodes.length - 1} />)}</div><div className="mt-4 grid grid-cols-2 gap-3"><button className="secondary-button gap-2" type="button" onClick={addStep}><Plus className="size-4" />Etapa</button><button className="secondary-button gap-2" type="button" onClick={addRepeat}><Repeat2 className="size-4" />Repetição</button></div></section>
      <ValidationPanel errors={totals.errors} />
      {existing && <Field label="Motivo da nova revisão"><input value={changeReason} maxLength={500} onChange={(event) => setChangeReason(event.target.value)} placeholder="Ex.: ajustar volume da série principal" /></Field>}
      {save.isError && <ErrorState message="Não foi possível salvar. Recarregue se outra revisão foi criada." />}{save.isSuccess && <SavedNotice>Revisão imutável salva.</SavedNotice>}
      <button className="primary-button gap-2" type="button" disabled={save.isPending || !definition.title || definition.nodes.length === 0} onClick={() => save.mutate()}><Save className="size-4" />{save.isPending ? "Salvando…" : existing ? "Salvar nova revisão" : "Criar rascunho"}</button>
      {existing && <RevisionAndSchedule workout={existing} approve={() => approve.mutate()} approvePending={approve.isPending} scheduleDate={scheduleDate} setScheduleDate={setScheduleDate} scheduleTime={scheduleTime} setScheduleTime={setScheduleTime} schedule={() => schedule.mutate()} schedulePending={schedule.isPending} />}
    </Page>
  );
}

function NodeEditor({ node, poolLength, onChange, onMove, onRemove, first, last }: { node: WorkoutNode; poolLength: number; onChange: (node: WorkoutNode) => void; onMove: (direction: -1 | 1) => void; onRemove: () => void; first: boolean; last: boolean }) {
  return <article className="workout-node"><div className="flex items-center gap-3"><span className="icon-chip">{node.type === "repeat" ? <Repeat2 className="size-5" /> : <Waves className="size-5" />}</span><div className="min-w-0 flex-1"><p className="font-semibold">{node.type === "repeat" ? "Grupo de repetição" : roleLabel(node.step_role ?? "WORK")}</p><p className="text-xs text-slate-500">{node.type === "repeat" ? `${node.repetitions} voltas` : endLabel(node)}</p></div><div className="flex"><IconButton label="Mover para cima" disabled={first} onClick={() => onMove(-1)}><ArrowUp /></IconButton><IconButton label="Mover para baixo" disabled={last} onClick={() => onMove(1)}><ArrowDown /></IconButton><IconButton label="Remover bloco" onClick={onRemove}><Trash2 /></IconButton></div></div>{node.type === "repeat" ? <RepeatFields node={node} poolLength={poolLength} onChange={onChange} /> : <StepFields node={node} poolLength={poolLength} onChange={onChange} />}</article>;
}

function StepFields({ node, poolLength, onChange }: { node: WorkoutStep; poolLength: number; onChange: (node: WorkoutStep) => void }) {
  const isDistance = node.end_condition.type === "distance";
  return <div className="mt-4 grid grid-cols-2 gap-3"><Field label="Tipo"><select value={node.step_role ?? "WORK"} onChange={(event) => { const role = event.target.value as WorkoutRole; onChange({ ...node, step_role: role, end_condition: role === "REST" ? { type: "time", seconds: 20 } : isDistance ? node.end_condition : { type: "distance", meters: poolLength * 2 } }); }}>{["WARMUP", "WORK", "DRILL", "RECOVERY", "REST", "COOLDOWN"].map((role) => <option key={role} value={role}>{roleLabel(role as WorkoutRole)}</option>)}</select></Field><Field label={node.step_role === "REST" ? "Segundos" : "Distância (m)"}><input type="number" min={node.step_role === "REST" ? 1 : poolLength} step={node.step_role === "REST" ? 1 : poolLength} value={node.end_condition.type === "distance" ? node.end_condition.meters : node.end_condition.type === "time" ? node.end_condition.seconds : 1} onChange={(event) => onChange({ ...node, end_condition: node.step_role === "REST" ? { type: "time", seconds: Number(event.target.value) } : { type: "distance", meters: Number(event.target.value) } })} /></Field></div>;
}

function RepeatFields({ node, poolLength, onChange }: { node: WorkoutRepeat; poolLength: number; onChange: (node: WorkoutRepeat) => void }) {
  return <div className="mt-4 grid gap-3"><Field label="Repetições"><input type="number" min="1" max="100" value={node.repetitions} onChange={(event) => onChange({ ...node, repetitions: Number(event.target.value) })} /></Field><div className="repeat-children">{node.children.map((child, index) => <div className="rounded-xl bg-white p-3" key={index}><p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Etapa {index + 1}</p>{child.type === "step" ? <StepFields node={child} poolLength={poolLength} onChange={(next) => onChange({ ...node, children: node.children.map((item, itemIndex) => itemIndex === index ? next : item) })} /> : <p className="text-sm">Repetição aninhada preservada no JSON canônico.</p>}</div>)}</div></div>;
}

function RevisionAndSchedule({ workout, approve, approvePending, scheduleDate, setScheduleDate, scheduleTime, setScheduleTime, schedule, schedulePending }: { workout: Workout; approve: () => void; approvePending: boolean; scheduleDate: string; setScheduleDate: (value: string) => void; scheduleTime: string; setScheduleTime: (value: string) => void; schedule: () => void; schedulePending: boolean }) {
  const currentApproved = workout.approved_revision_id === workout.current_revision_id;
  return <><section className="surface-card"><div className="flex items-start gap-4"><span className="icon-chip"><CopyPlus className="size-5" /></span><div><h2 className="section-title">Histórico imutável</h2><p className="mt-1 text-sm text-slate-600">{workout.revisions.length} revisões · hash {workout.current_revision.content_hash.slice(0, 12)}…</p></div></div><ol className="mt-5 grid gap-2">{workout.revisions.map((revision) => <li className="check-row" key={revision.id}><CheckCircle2 className="size-4" />Revisão {revision.revision_number} · {revision.validation.totals.distance_m.toLocaleString("pt-BR")} m</li>)}</ol>{!currentApproved && <button className="secondary-button mt-5 w-full gap-2" type="button" disabled={approvePending || !workout.current_revision.validation.valid} onClick={approve}><CheckCircle2 className="size-4" />{approvePending ? "Aprovando…" : "Aprovar esta revisão localmente"}</button>}</section><section className="surface-card form-stack"><div><p className="eyebrow">Calendário local</p><h2 className="section-title mt-1">Agendar sessão</h2></div><div className="grid grid-cols-2 gap-3"><Field label="Data"><input type="date" value={scheduleDate} onChange={(event) => setScheduleDate(event.target.value)} /></Field><Field label="Horário"><input type="time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} /></Field></div><button className="primary-button gap-2" type="button" disabled={!currentApproved || schedulePending} onClick={schedule}><CalendarCheck className="size-4" />{schedulePending ? "Agendando…" : workout.schedule ? "Reagendar treino" : "Agendar treino"}</button>{!currentApproved && <p className="text-sm text-amber-700">Aprove a revisão atual antes de agendar.</p>}</section></>;
}

function ValidationPanel({ errors }: { errors: string[] }) { return errors.length ? <section className="validation-panel validation-error"><AlertTriangle className="size-5" /><div><h2 className="font-bold">Revise antes de aprovar</h2>{errors.map((error) => <p className="mt-1 text-sm" key={error}>{error}</p>)}</div></section> : <section className="validation-panel"><CheckCircle2 className="size-5" /><div><h2 className="font-bold">Todas as distâncias terminam na parede</h2><p className="mt-1 text-sm">O domínio fará a mesma validação ao salvar.</p></div></section>; }
function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactElement }) { return <button className="icon-button" type="button" aria-label={label} disabled={disabled} onClick={onClick}>{children}</button>; }
function roleLabel(role: WorkoutRole) { return ({ WARMUP: "Aquecimento", WORK: "Nado", RECOVERY: "Recuperação", REST: "Descanso", COOLDOWN: "Soltura", DRILL: "Educativo", OTHER: "Outro" } as Record<WorkoutRole, string>)[role]; }
function endLabel(node: WorkoutStep) { return node.end_condition.type === "distance" ? `${node.end_condition.meters} m` : node.end_condition.type === "time" ? `${node.end_condition.seconds} s` : "Botão lap"; }
function Page({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) { return <div className="page-stack"><section><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1></section>{children}</div>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="grid gap-2 text-sm font-semibold text-slate-700"><span>{label}</span>{children}</label>; }

export function CalendarPage() {
  const workouts = useQuery({ queryKey: ["workouts"], queryFn: api.workouts });
  const [view, setView] = useState<"week" | "month">("week");
  if (workouts.isLoading) return <LoadingState label="Montando calendário…" />;
  if (!workouts.data) return <ErrorState message="Não foi possível carregar o calendário." />;
  const scheduled = workouts.data.filter((item) => item.schedule).sort((a, b) => a.schedule!.scheduled_date.localeCompare(b.schedule!.scheduled_date));
  return <Page title="Calendário" eyebrow="Agenda local · America/Sao_Paulo"><div className="segmented-control" aria-label="Visualização"><button className={view === "week" ? "active" : ""} onClick={() => setView("week")} type="button">Semana</button><button className={view === "month" ? "active" : ""} onClick={() => setView("month")} type="button">Mês</button></div>{scheduled.length ? <div className="grid gap-3">{scheduled.map((workout) => <Link className="surface-card workout-list-row" key={workout.id} to="/workouts/$workoutId" params={{ workoutId: workout.id }}><div><p className="eyebrow">{new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: view === "month" ? "long" : "short", timeZone: workout.schedule!.timezone }).format(new Date(`${workout.schedule!.scheduled_date}T12:00:00`))}</p><h2 className="section-title mt-2">{workout.title}</h2><p className="mt-1 text-sm text-slate-500">{workout.schedule!.scheduled_start_time?.slice(0, 5) ?? "Horário livre"} · {workout.current_revision.validation.totals.distance_m.toLocaleString("pt-BR")} m</p></div><TimerReset className="size-5 text-cyan-800" /></Link>)}</div> : <section className="empty-card"><CalendarCheck className="size-7 text-cyan-800" /><div><h2 className="section-title">Nenhum treino agendado</h2><p className="mt-2 text-sm text-slate-600">Aprove uma revisão e escolha a data no detalhe do treino.</p></div></section>}</Page>;
}
