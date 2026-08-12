import { AlertCircle, LoaderCircle } from "lucide-react";

export function LoadingState({ label = "Carregando seu contexto…" }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      <LoaderCircle className="size-6 animate-spin text-cyan-700" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state-panel border-red-200 bg-red-50 text-red-900" role="alert">
      <AlertCircle className="size-6" aria-hidden="true" />
      <div>
        <p className="font-semibold">Não conseguimos concluir agora.</p>
        <p className="mt-1 text-sm opacity-80">{message}</p>
      </div>
    </div>
  );
}

export function SavedNotice({ children }: { children: string }) {
  return (
    <p className="rounded-2xl bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-800" role="status">
      {children}
    </p>
  );
}
