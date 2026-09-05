"use client";
import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  Bot,
  Sparkles,
  Send,
  User,
  AlertTriangle,
  Layers,
  TrendingUp,
  Cpu,
  Clock,
  ArrowRight,
  ShieldCheck,
  RefreshCw
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge } from "@/app/components/ui/Badge";
import { queryAIAssistant, getAIInsights } from "@/lib/api";

interface ChatMessage {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: string;
  woLink?: string;
}

const QUICK_PROMPTS = [
  "Where are the production bottlenecks right now?",
  "Which work orders are at risk of delay?",
  "What is our overall plant yield?",
  "What is the status of WO-1001?",
  "How is machine utilization across our cells?",
  "How many parts are ready for dispatch?",
];

export default function AICopilotPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "1",
      sender: "ai",
      text: "Hello! I am your VSPL SMES Manufacturing Intelligence Copilot. I have real-time visibility into all active Work Orders, stage WIP balances, machine utilization, packing queues, and delay risks. How can I assist you today?",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [insights, setInsights] = useState<any[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getAIInsights()
      .then((data) => setInsights(data.insights || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async (queryText?: string) => {
    const q = queryText || input;
    if (!q.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: String(Date.now()),
      sender: "user",
      text: q.trim(),
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    if (!queryText) setInput("");
    setLoading(true);

    try {
      const res = await queryAIAssistant(q.trim());
      const aiMsg: ChatMessage = {
        id: String(Date.now() + 1),
        sender: "ai",
        text: res.answer,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, aiMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: String(Date.now() + 1),
        sender: "ai",
        text: "I encountered an issue querying the plant data. Please verify backend connectivity.",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-purple-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              AI Manufacturing Assistant
            </span>
            <span className="text-xs text-zinc-400">Context-Aware Plant LLM</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            VSPL SMES AI Copilot
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Ask natural language questions about work orders, delay risks, WIP buffers, quality defects, and machine performance.
          </p>
        </div>

        {/* Proactive Insights Cards */}
        {insights.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {insights.map((ins, i) => (
              <div
                key={i}
                className={`rounded-2xl p-4 border transition-all ${
                  ins.severity === "high"
                    ? "bg-rose-50/70 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/50"
                    : ins.severity === "medium"
                    ? "bg-amber-50/70 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/50"
                    : "bg-blue-50/70 dark:bg-blue-950/30 border-blue-200 dark:border-blue-900/50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span
                    className={`text-[10px] font-extrabold uppercase tracking-wider ${
                      ins.severity === "high"
                        ? "text-rose-600 dark:text-rose-400"
                        : ins.severity === "medium"
                        ? "text-amber-600 dark:text-amber-400"
                        : "text-blue-600 dark:text-blue-400"
                    }`}
                  >
                    {ins.title}
                  </span>
                  <span className="h-2 w-2 rounded-full bg-current" />
                </div>
                <p className="text-xs text-zinc-800 dark:text-zinc-200 font-medium mt-1.5 leading-relaxed">
                  {ins.description}
                </p>
                {ins.action_url && (
                  <Link
                    href={ins.action_url}
                    className="inline-flex items-center gap-1 text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:underline mt-2"
                  >
                    <span>View Tracking</span>
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Chat Container */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm flex flex-col h-[520px] overflow-hidden">
          {/* Message History */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex gap-3 ${m.sender === "user" ? "justify-end" : "justify-start"}`}
              >
                {m.sender === "ai" && (
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-purple-600 text-white shadow-sm font-bold text-xs">
                    <Bot className="h-4 w-4" />
                  </div>
                )}

                <div
                  className={`max-w-xl rounded-2xl p-4 text-xs leading-relaxed ${
                    m.sender === "user"
                      ? "bg-blue-600 text-white font-medium rounded-tr-none shadow-sm"
                      : "bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 rounded-tl-none border border-zinc-200/50 dark:border-zinc-700/50"
                  }`}
                >
                  <p className="whitespace-pre-line">{m.text}</p>
                  <span
                    className={`block text-[10px] mt-1.5 text-right ${
                      m.sender === "user" ? "text-blue-200" : "text-zinc-400"
                    }`}
                  >
                    {m.timestamp}
                  </span>
                </div>

                {m.sender === "user" && (
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 font-bold text-xs">
                    <User className="h-4 w-4" />
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-3 justify-start">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-purple-600 text-white shadow-sm">
                  <Bot className="h-4 w-4" />
                </div>
                <div className="rounded-2xl rounded-tl-none bg-zinc-100 dark:bg-zinc-800 p-4 text-xs text-zinc-500 flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full bg-purple-500 animate-ping" />
                  <span>Analyzing plant databases & OMS formulas...</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Prompt Chips */}
          <div className="border-t border-zinc-100 dark:border-zinc-800 p-3 bg-zinc-50/50 dark:bg-zinc-950/40 overflow-x-auto flex gap-2">
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => handleSend(prompt)}
                disabled={loading}
                className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-1 text-[11px] font-medium text-zinc-700 dark:text-zinc-300 hover:border-purple-500 hover:text-purple-600 dark:hover:text-purple-400 transition-colors whitespace-nowrap cursor-pointer"
              >
                {prompt}
              </button>
            ))}
          </div>

          {/* Input Box */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="p-4 border-t border-zinc-200 dark:border-zinc-800 flex gap-2 bg-white dark:bg-zinc-900"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything about work orders, bottlenecks, yield, or machines..."
              className="flex-1 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-4 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-purple-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="flex items-center justify-center rounded-xl bg-purple-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-purple-500 disabled:opacity-50 transition-colors cursor-pointer"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>
    </AppShell>
  );
}
