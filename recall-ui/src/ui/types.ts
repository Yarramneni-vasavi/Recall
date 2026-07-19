export type ChatRole = "user" | "assistant" | "system";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: number;
};

export type Conversation = {
  id: string;
  title: string;
  topic?: string;
  sessionId?: string;
  messages: ChatMessage[];
  lastUpdatedAt: number;
};

export type QuizQuestionType = "mcq" | "fill_blank";

export type QuizQuestion = {
  id: string;
  type: QuizQuestionType;
  text: string;
  options?: string[];
  difficulty?: number;
};

export type QuizState = {
  activeQuestion?: QuizQuestion;
  selectedTopics?: string[];
  lastResult?: {
    correct: boolean;
    feedback?: string;
  };
  loading: boolean;
  error?: string;
};
