import type { QuizQuestion } from "./types";

const DEFAULT_BASE = "http://localhost:8000";

function baseUrl() {
  const fromEnv = (import.meta as any).env?.VITE_API_BASE_URL as string | undefined;
  return (fromEnv ?? DEFAULT_BASE).replace(/\/+$/, "");
}

async function readJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!res.ok) {
    throw new Error(text || `HTTP ${res.status}`);
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(text || "Invalid JSON response");
  }
}

function normalizeQuestion(raw: any): QuizQuestion {
  const id = String(raw?.q_id ?? raw?.question_id ?? raw?.id ?? crypto.randomUUID());
  const text = String(raw?.text ?? raw?.question_text ?? raw?.prompt ?? "");
  const options: string[] | undefined = Array.isArray(raw?.options)
    ? raw.options.map((o: any) => String(o))
    : undefined;
  const type: "mcq" | "fill_blank" =
    raw?.type === "mcq" || (options && options.length > 0) ? "mcq" : "fill_blank";

  return {
    id,
    type,
    text,
    options: options && options.length ? options.slice(0, 4) : undefined,
    difficulty: typeof raw?.difficulty === "number" ? raw.difficulty : undefined
  };
}

export type StartSessionRequest = {
  sessionId: string;
  input: string;
};

export type StartSessionResponse = {
  topic?: string;
  level?: string;
  questions?: any[];
  batch_info?: { batch_num?: number; question_count?: number };
  clarification?: string;
};

export async function startSession(body: StartSessionRequest): Promise<{
  sessionId: string;
  questions: QuizQuestion[];
  topic?: string;
  level?: string;
  clarification?: string;
}> {
  const task = await startSessionTask(body);
  const done = await pollTask(task.taskId);
  const json = done.result as StartSessionResponse;
  return {
    sessionId: body.sessionId,
    questions: Array.isArray(json?.questions) ? (json.questions as any[]).map(normalizeQuestion) : [],
    topic: (json as any)?.topic ? String((json as any).topic) : undefined,
    level: (json as any)?.level ? String((json as any).level) : undefined,
    clarification: (json as any)?.clarification ? String((json as any).clarification) : undefined
  };
}

export type AnswerResponse = {
  feedback?: Array<{ q_id: string; correct: boolean; explanation?: string }>;
  batch_stats?: { accuracy?: number; questions_answered?: number };
  next_batch?: { level_adjustment?: string; total_questions_so_far?: number; continue_prompt?: string | null };
  scorecard_entry?: {
    topic: string;
    attempts: number;
    expertise: string;
    level_streak: number;
    ema_accuracy: number;
    last_accuracy: number;
    ema_difficulty: number;
    last_difficulty: number;
  } | null;
};

export async function submitAnswer(args: {
  sessionId: string;
  answers: Array<{ q_id: string; answer: string }>;
}): Promise<{
  feedback: Array<{ q_id: string; correct: boolean; explanation?: string }>;
  accuracy?: number;
  continuePrompt?: string | null;
  scorecardEntry?: {
    topic: string;
    attempts: number;
    expertise: string;
    levelStreak: number;
    emaAccuracy: number;
    lastAccuracy: number;
    emaDifficulty: number;
    lastDifficulty: number;
  } | null;
}> {
  const task = await submitAnswerTask(args);
  const done = await pollTask(task.taskId);
  const json = done.result as AnswerResponse;
  const fb = Array.isArray(json.feedback) ? json.feedback : [];
  return {
    feedback: fb.map((f: any) => ({
      q_id: String(f?.q_id ?? ""),
      correct: Boolean(f?.correct),
      explanation: f?.explanation ? String(f.explanation) : undefined
    })),
    accuracy: typeof json.batch_stats?.accuracy === "number" ? json.batch_stats.accuracy : undefined,
    continuePrompt: json.next_batch?.continue_prompt ?? null,
    scorecardEntry: json.scorecard_entry
      ? {
          topic: String((json.scorecard_entry as any).topic ?? ""),
          attempts: Number((json.scorecard_entry as any).attempts ?? 0),
          expertise: String((json.scorecard_entry as any).expertise ?? "beginner"),
          levelStreak: Number((json.scorecard_entry as any).level_streak ?? 0),
          emaAccuracy: Number((json.scorecard_entry as any).ema_accuracy ?? 0),
          lastAccuracy: Number((json.scorecard_entry as any).last_accuracy ?? 0),
          emaDifficulty: Number((json.scorecard_entry as any).ema_difficulty ?? 0),
          lastDifficulty: Number((json.scorecard_entry as any).last_difficulty ?? 0)
        }
      : null
  };
}

export type TaskStatus = {
  task_id: string;
  status: "pending" | "running" | "done" | "error";
  stage: string;
  result?: any;
  error?: string | null;
};

export async function getTask(taskId: string): Promise<TaskStatus> {
  const res = await fetch(`${baseUrl()}/tasks/${encodeURIComponent(taskId)}`);
  return readJson<TaskStatus>(res);
}

export async function pollTask(taskId: string, opts?: { intervalMs?: number; timeoutMs?: number }): Promise<TaskStatus> {
  const intervalMs = opts?.intervalMs ?? 400;
  const timeoutMs = opts?.timeoutMs ?? 120000;
  const start = Date.now();
  while (true) {
    const t = await getTask(taskId);
    if (t.status === "done") return t;
    if (t.status === "error") throw new Error(t.error || "Task failed");
    if (Date.now() - start > timeoutMs) throw new Error("Task timeout");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export async function startSessionTask(body: StartSessionRequest): Promise<{ taskId: string }> {
  const res = await fetch(`${baseUrl()}/quiz/${encodeURIComponent(body.sessionId)}/start_task`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input: body.input })
  });
  const task = await readJson<{ task_id: string }>(res);
  return { taskId: task.task_id };
}

export async function submitAnswerTask(args: {
  sessionId: string;
  answers: Array<{ q_id: string; answer: string }>;
}): Promise<{ taskId: string }> {
  const res = await fetch(`${baseUrl()}/quiz/${encodeURIComponent(args.sessionId)}/submit_task`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers: args.answers })
  });
  const task = await readJson<{ task_id: string }>(res);
  return { taskId: task.task_id };
}

export async function continueQuiz(args: { sessionId: string; action: string }): Promise<{ questions: QuizQuestion[] }> {
  const res = await fetch(`${baseUrl()}/quiz/${encodeURIComponent(args.sessionId)}/continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: args.action })
  });
  const json = await readJson<{ questions?: any[] }>(res);
  return { questions: Array.isArray(json.questions) ? json.questions.map(normalizeQuestion) : [] };
}

export async function getScorecard(limit = 50): Promise<
  Array<{
    topic: string;
    attempts: number;
    expertise?: string;
    levelStreak?: number;
    emaAccuracy: number;
    lastAccuracy: number;
    emaDifficulty: number;
    lastDifficulty: number;
  }>
> {
  const res = await fetch(`${baseUrl()}/scorecard?limit=${encodeURIComponent(String(limit))}`);
  const json = await readJson<{ items?: any[] }>(res);
  const items = Array.isArray(json.items) ? json.items : [];
  return items.map((s: any) => ({
    topic: String(s?.topic ?? ""),
    attempts: Number(s?.attempts ?? 0),
    expertise: s?.expertise ? String(s.expertise) : undefined,
    levelStreak: typeof s?.level_streak === "number" ? s.level_streak : undefined,
    emaAccuracy: Number(s?.ema_accuracy ?? 0),
    lastAccuracy: Number(s?.last_accuracy ?? 0),
    emaDifficulty: Number(s?.ema_difficulty ?? 0),
    lastDifficulty: Number(s?.last_difficulty ?? 0)
  }));
}

export async function getUiState(): Promise<{ conversations: any[] }> {
  const res = await fetch(`${baseUrl()}/ui/state`);
  const json = await readJson<{ conversations?: any[] }>(res);
  return { conversations: Array.isArray(json.conversations) ? json.conversations : [] };
}

export async function saveUiState(conversations: any[]): Promise<void> {
  const res = await fetch(`${baseUrl()}/ui/state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversations })
  });
  await readJson<any>(res);
}

export async function getCurrentQuiz(sessionId: string): Promise<any> {
  const res = await fetch(`${baseUrl()}/quiz/${encodeURIComponent(sessionId)}/current`);
  return readJson<any>(res);
}

export async function getQuizReview(sessionId: string): Promise<any> {
  const res = await fetch(`${baseUrl()}/quiz/${encodeURIComponent(sessionId)}/review`);
  return readJson<any>(res);
}
