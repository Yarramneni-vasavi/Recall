import React, { useEffect, useMemo, useState } from "react";
import type { ChatMessage, Conversation, QuizQuestion, QuizState } from "./types";
import {
  continueQuiz,
  getScorecard,
  getTask,
  getCurrentQuiz,
  getQuizReview,
  getUiState,
  saveUiState,
  startSessionTask,
  submitAnswerTask,
} from "./api";

function now() {
  return Date.now();
}

function fmtTime(ts: number) {
  const d = new Date(ts);
  return d.toLocaleString([], { hour: "2-digit", minute: "2-digit" });
}

function shortTitle(topic?: string) {
  const t = (topic ?? "").trim();
  if (!t) return "New conversation";
  return t.length > 42 ? `${t.slice(0, 42)}…` : t;
}

function defaultConversation(): Conversation {
  const id = crypto.randomUUID();
  const createdAt = now();
  return {
    id,
    title: "New conversation",
    messages: [
      {
        id: crypto.randomUUID(),
        role: "assistant",
        content:
          "Tell me what you want to revise. I’ll use your conversation to set the topic, then start a quiz on the right.",
        createdAt
      }
    ],
    lastUpdatedAt: createdAt
  };
}

function inferTopic(messages: ChatMessage[]): string | undefined {
  const firstUser = messages.find((m) => m.role === "user")?.content?.trim();
  if (!firstUser) return undefined;
  const topic = firstUser.split("\n").find(Boolean)?.trim();
  return topic && topic.length <= 140 ? topic : topic?.slice(0, 140);
}

function topicKey(topic: string) {
  return (topic ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function expertiseLabel(expertise?: string): "beginner" | "intermediate" | "advanced" {
  if (expertise === "advanced") return "advanced";
  if (expertise === "intermediate") return "intermediate";
  return "beginner";
}

function dotStyle(level: "beginner" | "intermediate" | "advanced") {
  if (level === "advanced") {
    return { background: "rgba(22, 163, 74, 0.9)", boxShadow: "0 0 0 3px rgba(22, 163, 74, 0.16)" };
  }
  if (level === "intermediate") {
    return { background: "rgba(245, 158, 11, 0.95)", boxShadow: "0 0 0 3px rgba(245, 158, 11, 0.18)" };
  }
  return { background: "rgba(239, 68, 68, 0.92)", boxShadow: "0 0 0 3px rgba(239, 68, 68, 0.16)" };
}

export function App() {
  async function pollTaskInUi(taskId: string): Promise<any> {
    const start = Date.now();
    while (true) {
      const t = await getTask(taskId);
      setStage(t.stage || null);
      if (t.status === "done") return t.result;
      if (t.status === "error") throw new Error(t.error || "Task failed");
      if (Date.now() - start > 120000) throw new Error("Task timeout");
      await new Promise((r) => setTimeout(r, 20000));
    }
  }

  const [conversations, setConversations] = useState<Conversation[]>(() => [defaultConversation()]);
  const [activeId, setActiveId] = useState<string>(() => conversations[0]!.id);

  const active = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? conversations[0],
    [conversations, activeId]
  );

  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [scorecard, setScorecard] = useState<Record<string, any>>(() => ({}));

  const [quiz, setQuiz] = useState<QuizState>({ loading: false });
  const [answerText, setAnswerText] = useState("");
  const [selectedOpt, setSelectedOpt] = useState<number | null>(null);
  const [batch, setBatch] = useState<QuizQuestion[] | null>(null);
  const [batchIdx, setBatchIdx] = useState(0);
  const [batchAnswers, setBatchAnswers] = useState<Record<string, string>>({});
  const [continueMode, setContinueMode] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [ended, setEnded] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewItems, setReviewItems] = useState<any[] | null>(null);
  const [reviewSummary, setReviewSummary] = useState<{ strong: string[]; weak: string[] } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const state = await getUiState();
        if (cancelled) return;
        const list = (state.conversations as any[]).filter((c) => c && typeof c.id === "string" && Array.isArray(c.messages));
        const next = (list.length ? (list as Conversation[]) : [defaultConversation()]).slice().sort((a, b) => b.lastUpdatedAt - a.lastUpdatedAt);
        setConversations(next);
        setActiveId(next[0]!.id);
      } catch {
        // keep default
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const t = setTimeout(() => {
      saveUiState(conversations as any).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [conversations]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const items = await getScorecard(50);
        if (cancelled) return;
        const map: Record<string, any> = {};
        for (const it of items) {
          const key = topicKey(it.topic);
          if (!key) continue;
          map[key] = {
            topic: it.topic,
            attempts: it.attempts,
            expertise: it.expertise,
            levelStreak: it.levelStreak,
            emaAccuracy: it.emaAccuracy,
            lastAccuracy: it.lastAccuracy,
            emaDifficulty: it.emaDifficulty,
            lastDifficulty: it.lastDifficulty,
            lastUpdatedAt: Date.now()
          };
        }
        setScorecard(map);
      } catch {
        // keep local cache
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setQuiz((q) => ({ ...q, error: undefined }));
    setAnswerText("");
    setSelectedOpt(null);
    setBatch(null);
    setBatchIdx(0);
    setBatchAnswers({});
    setContinueMode(false);
    setStage(null);
    setEnded(false);
    setReviewOpen(false);
    setReviewItems(null);
    setReviewSummary(null);
  }, [activeId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!active?.sessionId) return;
        const cur = await getCurrentQuiz(active.sessionId);
        if (cancelled) return;
        if (cur?.clarification) {
          setQuiz({ loading: false, error: undefined, activeQuestion: undefined });
          return;
        }
        if (cur?.continue_prompt) {
          setContinueMode(true);
          setBatch(null);
          setBatchIdx(0);
          setBatchAnswers({});
          setQuiz({
            loading: false,
            activeQuestion: { id: "__continue__", type: "fill_blank", text: String(cur.continue_prompt) },
            lastResult: undefined
          });
          return;
        }
        if (cur?.ended) {
          setEnded(true);
          setBatch(null);
          setBatchIdx(0);
          setBatchAnswers({});
          setContinueMode(false);
          setQuiz({ loading: false, error: String(cur?.message ?? "Questions limit reached for this session."), activeQuestion: undefined });
          return;
        }
        const qs = Array.isArray(cur?.questions)
          ? cur.questions.map((q: any) => ({
              id: String(q?.q_id ?? crypto.randomUUID()),
              type: q?.type === "mcq" || (Array.isArray(q?.options) && q.options.length) ? "mcq" : "fill_blank",
              text: String(q?.text ?? q?.question_text ?? ""),
              options: Array.isArray(q?.options) ? q.options.map(String).slice(0, 4) : undefined
            }))
          : [];
        setBatch(qs);
        setBatchIdx(0);
        setBatchAnswers({});
        setContinueMode(false);
        setQuiz((prev) => ({ ...prev, loading: false, activeQuestion: qs[0] }));
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, active?.sessionId]);

  function patchActive(patch: (c: Conversation) => Conversation) {
    setConversations((prev) => {
      const next = prev.map((c) => (c.id === activeId ? patch(c) : c));
      return next.slice().sort((a, b) => b.lastUpdatedAt - a.lastUpdatedAt);
    });
  }

  async function ensureSession(
    inputText: string
  ): Promise<{ sessionId: string; question?: QuizQuestion } | { kind: "clarification"; message: string } | null> {
    if (!active) return null;
    if (active.sessionId) return { sessionId: active.sessionId, question: quiz.activeQuestion };

    setQuiz({ loading: true });
    setStage("parsing");
    try {
      const task = await startSessionTask({
        sessionId: active.id,
        input: inputText
      });
      const started = await pollTaskInUi(task.taskId);
      if (!started) throw new Error("Missing session start result");
      if (started.clarification) {
        setQuiz({ loading: false, error: undefined, activeQuestion: undefined });
        setStage(null);
        return { kind: "clarification", message: String(started.clarification) };
      }

      patchActive((c) => ({
        ...c,
        sessionId: active.id,
        topic: started.topic ?? c.topic,
        title: shortTitle(started.topic ?? c.topic),
        lastUpdatedAt: now()
      }));

      const qs = Array.isArray(started.questions)
        ? started.questions.map((q: any) => ({
            id: String(q?.q_id ?? crypto.randomUUID()),
            type: q?.type === "mcq" || (Array.isArray(q?.options) && q.options.length) ? "mcq" : "fill_blank",
            text: String(q?.text ?? q?.question_text ?? ""),
            options: Array.isArray(q?.options) ? q.options.map(String).slice(0, 4) : undefined
          }))
        : [];
      setBatch(qs);
      setBatchIdx(0);
      setBatchAnswers({});
      setContinueMode(false);
      setQuiz({
        loading: false,
        activeQuestion: qs[0],
        selectedTopics: started.topic ? [started.topic] : undefined
      });
      setStage(null);
      return { sessionId: active.id, question: qs[0] };
    } catch (e: any) {
      setQuiz({ loading: false, error: e?.message ?? "Failed to start session" });
      setStage(null);
      return null;
    }
  }

  async function onSendMessage() {
    if (!active) return;
    const content = composer.trim();
    if (!content) return;
    setComposer("");
    setSending(true);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      createdAt: now()
    };

    patchActive((c) => ({
      ...c,
      messages: [...c.messages, userMsg],
      lastUpdatedAt: now()
    }));

    const session = await ensureSession(content);

    patchActive((c) => ({
      ...c,
      messages: [
        ...c.messages,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: session && (session as any).kind === "clarification" ? (session as any).message : (session as any)?.sessionId
            ? "Topic set. Answer the question on the right to continue."
            : "I couldn’t start a quiz session. Check API base URL and server.",
          createdAt: now()
        }
      ],
      lastUpdatedAt: now()
    }));

    setSending(false);
  }

  async function onSubmitAnswer() {
    if (!active?.sessionId) {
      setQuiz((q) => ({ ...q, error: "Send a message first to start the quiz." }));
      return;
    }
    if (ended) {
      setQuiz((q) => ({ ...q, error: "Questions limit reached for this session." }));
      return;
    }
    const session = { sessionId: active.sessionId };

    const q = quiz.activeQuestion;
    if (!q) {
      setQuiz((s) => ({ ...s, error: "No active question yet." }));
      return;
    }

    const answer =
      q.type === "mcq" ? (selectedOpt == null ? "" : String(q.options?.[selectedOpt] ?? "")) : answerText.trim();
    if (!answer) return;

    setQuiz((s) => ({ ...s, loading: true, error: undefined }));
    try {
      const trimmed = answer.trim();
      if (continueMode) {
        const next = await continueQuiz({ sessionId: session.sessionId, action: trimmed });
        setBatch(next.questions);
        setBatchIdx(0);
        setBatchAnswers({});
        setContinueMode(false);
        setQuiz({ loading: false, activeQuestion: next.questions[0], lastResult: undefined });
        setAnswerText("");
        setSelectedOpt(null);
        return;
      }

      const nextAnswers = { ...batchAnswers, [q.id]: trimmed };
      setBatchAnswers(nextAnswers);

      const currentBatch = batch ?? [];
      const nextIdx = batchIdx + 1;
      if (nextIdx < currentBatch.length) {
        setBatchIdx(nextIdx);
        setQuiz({ loading: false, activeQuestion: currentBatch[nextIdx], lastResult: undefined });
        setAnswerText("");
        setSelectedOpt(null);
        return;
      }

      const payload = currentBatch.map((qq) => ({ q_id: qq.id, answer: nextAnswers[qq.id] ?? "" }));
      setStage("judging");
      const task = await submitAnswerTask({ sessionId: session.sessionId, answers: payload });
      const judged = await pollTaskInUi(task.taskId);

      const weak = Array.isArray(judged?.weak_areas)
        ? judged.weak_areas.map(String).filter((s: string) => s.trim()).slice(0, 6)
        : [];
      setQuiz((q) => ({ ...q, weakAreas: weak.length ? weak : undefined }));
      if (judged?.scorecard_entry) {
        setScorecard((prev) => ({
          ...prev,
          [topicKey(String(judged.scorecard_entry.topic ?? ""))]: {
            topic: judged.scorecard_entry.topic,
            attempts: judged.scorecard_entry.attempts,
            expertise: judged.scorecard_entry.expertise,
            levelStreak: judged.scorecard_entry.level_streak,
            emaAccuracy: judged.scorecard_entry.ema_accuracy,
            lastAccuracy: judged.scorecard_entry.last_accuracy,
            emaDifficulty: judged.scorecard_entry.ema_difficulty,
            lastDifficulty: judged.scorecard_entry.last_difficulty,
            lastUpdatedAt: Date.now()
          }
        }));
      }

      if (judged?.ended || judged?.error === "questions_limit_reached") {
        setEnded(true);
        setQuiz((q) => ({ ...q, loading: false, error: judged?.message ?? "Questions limit reached for this session." }));
        return;
      }

      const continuePrompt = judged?.next_batch?.continue_prompt ?? null;
      const accuracy = judged?.batch_stats?.accuracy;
      if (continuePrompt) {
        setContinueMode(true);
        setBatch(null);
        setBatchIdx(0);
        setBatchAnswers({});
        setQuiz({
          loading: false,
          activeQuestion: { id: "__continue__", type: "fill_blank", text: continuePrompt },
          lastResult: {
            correct: (accuracy ?? 0) >= 0.75,
            feedback:
              typeof accuracy === "number" ? `Batch accuracy: ${(accuracy * 100).toFixed(0)}%` : undefined
          }
        });
        setAnswerText("");
        setSelectedOpt(null);
        setStage(null);
        return;
      }

      const next = await continueQuiz({ sessionId: session.sessionId, action: "yes" });
      setBatch(next.questions);
      setBatchIdx(0);
      setBatchAnswers({});
      setQuiz({
        loading: false,
        activeQuestion: next.questions[0],
        lastResult: {
          correct: (accuracy ?? 0) >= 0.75,
          feedback:
            typeof accuracy === "number" ? `Batch accuracy: ${(accuracy * 100).toFixed(0)}%` : undefined
        }
      });
      setAnswerText("");
      setSelectedOpt(null);
      setStage(null);
    } catch (e: any) {
      setQuiz((s) => ({ ...s, loading: false, error: e?.message ?? "Failed to submit answer" }));
      setStage(null);
    }
  }

  async function onToggleReview() {
    if (!active?.sessionId) return;
    const next = !reviewOpen;
    setReviewOpen(next);
    if (next) {
      try {
        const res = await getQuizReview(active.sessionId);
        setReviewItems(Array.isArray(res?.items) ? res.items : []);
        setReviewSummary({
          strong: Array.isArray(res?.strong_areas) ? res.strong_areas.map(String).filter((s: string) => s.trim()).slice(0, 6) : [],
          weak: Array.isArray(res?.weak_areas) ? res.weak_areas.map(String).filter((s: string) => s.trim()).slice(0, 6) : []
        });
      } catch {
        setReviewItems([]);
        setReviewSummary({ strong: [], weak: [] });
      }
    } else {
      setReviewSummary(null);
    }
  }

  function onNewConversation() {
    const c = defaultConversation();
    setConversations((prev) => [c, ...prev]);
    setActiveId(c.id);
    setQuiz({ loading: false });
    setAnswerText("");
    setSelectedOpt(null);
  }

  const topic = active?.topic ?? inferTopic(active?.messages ?? []);
  const activeScore = topic ? scorecard[topicKey(topic)] : undefined;
  const topScores = useMemo(() => {
    const entries = Object.values(scorecard || {});
    entries.sort((a, b) => (b.lastUpdatedAt ?? 0) - (a.lastUpdatedAt ?? 0));
    return entries.slice(0, 6);
  }, [scorecard]);

  return (
    <div className="app">
      <aside className="card sidebar">
        <div className="sidebarHeader">
          <div className="row" style={{ gap: 10 }}>
            <div className="logoMark" aria-hidden="true" title="RECALL">
              <svg viewBox="0 0 24 24" fill="none">
                <path
                  d="M6.5 7.5c0-2.2 2.2-4 5.5-4s5.5 1.8 5.5 4-2.2 4-5.5 4-5.5-1.8-5.5-4Z"
                  stroke="rgba(255,255,255,0.95)"
                  strokeWidth="1.6"
                />
                <path
                  d="M6.5 7.7v8.9c0 2.2 2.2 4 5.5 4s5.5-1.8 5.5-4V7.7"
                  stroke="rgba(255,255,255,0.95)"
                  strokeWidth="1.6"
                />
                <path
                  d="M8.2 12.2c1 .9 2.5 1.5 3.8 1.5s2.8-.6 3.8-1.5"
                  stroke="rgba(255,255,255,0.95)"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div className="brand">
              <div className="brandTitle">RECALL</div>
              <div className="brandSub">revise smarter, not longer.</div>
            </div>
          </div>
          <button className="btn btnPrimary" onClick={onNewConversation}>
            New
          </button>
        </div>
        <div className="sidebarList">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`convItem ${c.id === activeId ? "convItemActive" : ""}`}
              onClick={() => setActiveId(c.id)}
              role="button"
              tabIndex={0}
            >
              <div className="convTitleRow">
                <div className="convTitle">{c.title || "Untitled"}</div>
                <div className="convMeta">{fmtTime(c.lastUpdatedAt)}</div>
              </div>
              <div className="convMeta">{c.topic ? c.topic : "No topic yet"}</div>
            </div>
          ))}
        </div>
      </aside>

      <section className="card main">
        <div className="mainHeader">
          <div className="muted" style={{ fontSize: 12 }}>
            API: <span style={{ fontFamily: "var(--mono)" }}>{(import.meta as any).env?.VITE_API_BASE_URL ?? "http://localhost:8000"}</span>
          </div>
          {stage ? (
            <div className="muted" style={{ fontSize: 12 }}>
              Status: <span style={{ fontFamily: "var(--mono)" }}>{stage}</span>
            </div>
          ) : null}
        </div>
        <div className="chatBody">
          {active?.messages.map((m) => (
            <div key={m.id} className={`msg ${m.role === "user" ? "msgUser" : "msgAssistant"}`}>
              {m.content}
              <div className="msgMeta">
                {m.role} · {fmtTime(m.createdAt)}
              </div>
            </div>
          ))}
        </div>
        <div className="chatComposer">
          {stage ? (
            <div className="row" style={{ gap: 8, alignItems: "center", marginBottom: 6 }}>
              <div
                aria-label="Loading"
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 999,
                  border: "2px solid rgba(15, 23, 42, 0.18)",
                  borderTopColor: "rgba(79, 70, 229, 0.9)",
                  animation: "spin 0.9s linear infinite"
                }}
              />
              <div className="muted" style={{ fontSize: 12 }}>
                Processing: {stage}
              </div>
            </div>
          ) : null}
          <textarea
            value={composer}
            onChange={(e) => setComposer(e.target.value)}
            disabled={ended}
            placeholder="Type a message… (first user message becomes the topic)"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSendMessage();
            }}
          />
          <button className="btn btnPrimary" onClick={onSendMessage} disabled={ended || sending || !composer.trim()}>
            Send
          </button>
        </div>
      </section>

      <section className="card right">
        <div className="banner" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="bannerTitle">Scorecard</div>
          <div className="bannerSub">Across sessions, per topic.</div>

          {topic && activeScore ? null : null}

          {topScores.length ? (
            <div className="topicsRow" aria-label="All topic scores">
              {topScores.map((s) => (
                <div className="chip" key={topicKey(s.topic)} title="Across sessions">
                  <span className="chipDot" aria-hidden="true" style={dotStyle(expertiseLabel(s.expertise))} />
                  <span>
                    {s.topic}: {(s.emaAccuracy * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="banner">
          <div className="bannerTitle">Quiz</div>
          <div className="bannerSub">
            {topic ? (
              <>
                Topic selected from conversation: <strong>{topic}</strong>
              </>
            ) : (
              "Send a message on the left to set a topic and start the quiz."
            )}
          </div>
          <div className="row" style={{ marginTop: 10, justifyContent: "space-between" }}>
            <button className="btn" onClick={onToggleReview} disabled={!active?.sessionId}>
              {reviewOpen ? "Back" : "Review answers"}
            </button>
          </div>

          {quiz.selectedTopics?.length ? (
            <div className="topicsRow" aria-label="Selected topics">
              {quiz.selectedTopics.map((t, idx) => (
                <div className="chip" key={`${t}:${idx}`}>
                  <span className="chipDot" aria-hidden="true" />
                  <span>{t}</span>
                </div>
              ))}
            </div>
          ) : null}

          {topic && activeScore ? (
            <div className="topicsRow" aria-label="Scorecard">
              <div className="chip" title="Rolling score across sessions for this topic">
                <span
                  className="chipDot"
                  aria-hidden="true"
                  style={dotStyle(expertiseLabel(activeScore.expertise))}
                />
                <span>
                  Score: {(activeScore.emaAccuracy * 100).toFixed(0)}% · {expertiseLabel(activeScore.expertise)} · attempts{" "}
                  {activeScore.attempts}
                </span>
              </div>
            </div>
          ) : null}

          {false ? (
            <div className="topicsRow" aria-label="All topic scores">
              {topScores.map((s) => (
                <div className="chip" key={topicKey(s.topic)} title="Across sessions">
                  <span
                    className="chipDot"
                    aria-hidden="true"
                    style={dotStyle(expertiseLabel(s.expertise))}
                  />
                  <span>
                    {s.topic}: {(s.emaAccuracy * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="quizBody">
          {quiz.error ? (
            <div className="questionCard">
              <div className="qText" style={{ color: "var(--danger)" }}>
                {quiz.error}
              </div>
            </div>
          ) : null}

          {reviewOpen && reviewSummary && (reviewSummary.strong.length || reviewSummary.weak.length) ? (
            <div className="questionCard">
              <div className="qText">Strengths & Weaknesses</div>
              <div className="qType">Derived from your answers so far.</div>
              {reviewSummary.strong.length ? (
                <div style={{ marginTop: 10 }}>
                  <div className="qType" style={{ fontWeight: 650 }}>Strong areas</div>
                  <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {reviewSummary.strong.map((w, i) => (
                      <div className="chip" key={`s:${w}:${i}`}>
                        <span className="chipDot" aria-hidden="true" style={{ background: "rgba(22, 163, 74, 0.9)", boxShadow: "0 0 0 3px rgba(22, 163, 74, 0.16)" }} />
                        <span>{w}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {reviewSummary.weak.length ? (
                <div style={{ marginTop: 12 }}>
                  <div className="qType" style={{ fontWeight: 650 }}>Weak areas</div>
                  <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {reviewSummary.weak.map((w, i) => (
                      <div className="chip" key={`w:${w}:${i}`}>
                        <span className="chipDot" aria-hidden="true" style={{ background: "rgba(239, 68, 68, 0.92)", boxShadow: "0 0 0 3px rgba(239, 68, 68, 0.16)" }} />
                        <span>{w}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {reviewOpen ? (
            <div className="questionCard">
              <div className="qText">Review</div>
              <div className="qType">Previous questions for this session.</div>
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
                {(reviewItems ?? []).length ? (
                  (reviewItems ?? []).slice().reverse().map((it: any) => {
                    const ok = Boolean(it?.correct);
                    const border = ok ? "rgba(22, 163, 74, 0.35)" : "rgba(239, 68, 68, 0.35)";
                    const bg = ok ? "rgba(22, 163, 74, 0.06)" : "rgba(239, 68, 68, 0.06)";
                    return (
                      <div
                        key={String(it?.q_id ?? crypto.randomUUID())}
                        style={{
                          border: `1px solid ${border}`,
                          background: bg,
                          borderRadius: 12,
                          padding: 10
                        }}
                      >
                        <div style={{ fontWeight: 650 }}>{String(it?.question_text ?? "")}</div>
                        <div className="qType" style={{ marginTop: 6 }}>
                          Your answer: <span style={{ fontFamily: "var(--mono)" }}>{String(it?.user_answer ?? "")}</span>
                        </div>
                        {it?.correct_answer ? (
                          <div className="qType">
                            Correct answer:{" "}
                            <span style={{ fontFamily: "var(--mono)" }}>{String(it.correct_answer)}</span>
                          </div>
                        ) : null}
                        {it?.explanation ? <div className="qType">Explanation: {String(it.explanation)}</div> : null}
                      </div>
                    );
                  })
                ) : (
                  <div className="qType">No answers yet.</div>
                )}
              </div>
            </div>
          ) : null}

          {!quiz.activeQuestion && !quiz.error ? (
            <div className="questionCard">
              <div className="qText">No question yet</div>
              <div className="qType">Start by sending a message on the left (topic), then answer here.</div>
            </div>
          ) : null}

          {quiz.activeQuestion && !reviewOpen ? (
            <QuestionView
              question={quiz.activeQuestion}
              loading={quiz.loading}
              answerText={answerText}
              onAnswerText={setAnswerText}
              selectedOpt={selectedOpt}
              onSelectOpt={setSelectedOpt}
              onSubmit={onSubmitAnswer}
              lastResult={quiz.lastResult}
            />
          ) : null}
        </div>
      </section>
    </div>
  );
}

function QuestionView(props: {
  question: QuizQuestion;
  loading: boolean;
  answerText: string;
  onAnswerText: (v: string) => void;
  selectedOpt: number | null;
  onSelectOpt: (v: number | null) => void;
  onSubmit: () => void;
  lastResult?: { correct: boolean; feedback?: string };
}) {
  const q = props.question;
  const typeLabel = q.type === "mcq" ? "Choose the correct answer" : "Fill in the blank";

  return (
    <div className="questionCard">
      <div className="qText">{q.text}</div>
      <div className="qType">
        {typeLabel}
        {typeof q.difficulty === "number" ? <span className="muted"> · difficulty {q.difficulty.toFixed(1)}</span> : null}
      </div>

      {q.type === "mcq" ? (
        <div className="options">
          {(q.options ?? []).slice(0, 4).map((opt, idx) => (
            <div
              key={`${q.id}:${idx}`}
              className={`opt ${props.selectedOpt === idx ? "optSelected" : ""}`}
              onClick={() => props.onSelectOpt(idx)}
              role="button"
              tabIndex={0}
            >
              <div style={{ width: 18, fontFamily: "var(--mono)", color: "var(--muted)" }}>{String.fromCharCode(65 + idx)}</div>
              <div className="grow">{opt}</div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ marginTop: 12 }}>
          <textarea
            value={props.answerText}
            onChange={(e) => props.onAnswerText(e.target.value)}
            placeholder="Type your answer…"
          />
        </div>
      )}

      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn btnPrimary" onClick={props.onSubmit} disabled={props.loading}>
          {props.loading ? "Checking…" : "Submit"}
        </button>
        <div className="muted" style={{ fontSize: 12 }}>
          {q.type === "mcq"
            ? props.selectedOpt == null
              ? "Select one option."
              : "Ready to submit."
            : props.answerText.trim()
              ? "Ready to submit."
              : "Enter an answer."}
        </div>
      </div>

      {props.lastResult ? (
        <div className={`feedback ${props.lastResult.correct ? "feedbackOk" : "feedbackBad"}`}>
          <div style={{ fontWeight: 650 }}>{props.lastResult.correct ? "Correct" : "Not quite"}</div>
          {props.lastResult.feedback ? <div style={{ marginTop: 6 }}>{props.lastResult.feedback}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
