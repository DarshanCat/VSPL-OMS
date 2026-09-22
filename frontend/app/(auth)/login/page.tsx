"use client";
import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { Factory, Lock, Mail, ArrowRight, ShieldCheck, CheckCircle2 } from "lucide-react";
import { login } from "@/lib/api";

const DEMO_ROLES = [
  { role: "Production Manager", email: "pm@vspl.com", pass: "pm123" },
  { role: "Lead Planner", email: "planner@vspl.com", pass: "planner123" },
  { role: "Quality / QA", email: "qa@vspl.com", pass: "qa123" },
  { role: "Dispatch Officer", email: "dispatch@vspl.com", pass: "dispatch123" },
  { role: "CEO Executive", email: "ceo@vspl.com", pass: "ceo123" },
  { role: "Machine Operator", email: "operator@vspl.com", pass: "op123" },
];

// Demo credential quick-fill is a development/UAT convenience only. It must never render
// in a production build, since it would expose seed account passwords to anyone who can
// load the login page.
const SHOW_DEMO_LOGINS = process.env.NODE_ENV !== "production";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Invalid email or password. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  const quickFill = (em: string, pw: string) => {
    setEmail(em);
    setPassword(pw);
  };

  return (
    <div className="flex min-h-screen flex-col lg:flex-row bg-zinc-950 text-zinc-100">
      {/* Left hero banner */}
      <div className="relative hidden w-1/2 flex-col justify-between p-12 lg:flex border-r border-zinc-800 bg-gradient-to-br from-zinc-900 via-zinc-950 to-blue-950/40">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 font-bold text-white shadow-lg shadow-blue-500/30 text-xl">
            V
          </div>
          <div>
            <span className="text-lg font-bold tracking-tight">Vijay Spheroidals Pvt Ltd</span>
            <p className="text-xs text-blue-400 font-medium">Smart Manufacturing Execution System</p>
          </div>
        </div>

        <div className="max-w-md space-y-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-400">
            <Factory className="h-3.5 w-3.5" />
            <span>Centrifugal Bronze Castings MES</span>
          </div>
          <h2 className="text-3xl font-extrabold tracking-tight text-white leading-tight">
            AI Powered Production Tracking, Planning & Manufacturing Intelligence
          </h2>
          <p className="text-sm text-zinc-400 leading-relaxed">
            Real-time physical part movement tracking, auditable stage-level WIP, Packing / BSR verification, strict dispatch validation, and OMS Engine reporting.
          </p>

          <div className="space-y-3 pt-4">
            <div className="flex items-center gap-3 text-xs text-zinc-300">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <span>Real-time partial stage movement & route validation</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-zinc-300">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <span>Dedicated Packing / BSR stage before dispatch</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-zinc-300">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <span>Seamless integration with deterministic OMS Engine</span>
            </div>
          </div>
        </div>

        <div className="text-xs text-zinc-500">
          © 2026 Vijay Spheroidals Pvt Ltd. All rights reserved.
        </div>
      </div>

      {/* Right form */}
      <div className="flex flex-1 items-center justify-center p-6 lg:p-12">
        <div className="w-full max-w-md space-y-8">
          <div>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 font-bold text-white shadow-lg shadow-blue-500/30 text-xl lg:hidden mb-4">
              V
            </div>
            <h2 className="text-2xl font-bold tracking-tight text-white">Sign in to SMES</h2>
            <p className="mt-1 text-xs text-zinc-400">
              Enter your credentials to access the manufacturing execution portal.
            </p>
          </div>

          {error && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-medium text-rose-400">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs font-semibold text-zinc-300">Email Address</label>
              <div className="relative mt-1.5">
                <Mail className="absolute left-3.5 top-3 h-4 w-4 text-zinc-500" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@vspl.com"
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900/90 pl-10 pr-4 py-2.5 text-xs text-white placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 transition-all"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-300">Password</label>
              <div className="relative mt-1.5">
                <Lock className="absolute left-3.5 top-3 h-4 w-4 text-zinc-500" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900/90 pl-10 pr-4 py-2.5 text-xs text-white placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 transition-all"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3 text-xs font-bold text-white shadow-md shadow-blue-500/20 hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-zinc-900 disabled:opacity-50 transition-all cursor-pointer"
            >
              {loading ? (
                <span>Authenticating...</span>
              ) : (
                <>
                  <span>Sign In to Plant</span>
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </form>

          {/* Quick Demo Role Fillers -- development/UAT builds only */}
          {SHOW_DEMO_LOGINS && (
            <div className="pt-4 border-t border-zinc-800">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">
                Quick Role Test Logins:
              </p>
              <div className="grid grid-cols-2 gap-2">
                {DEMO_ROLES.map((r) => (
                  <button
                    key={r.email}
                    type="button"
                    onClick={() => quickFill(r.email, r.pass)}
                    className="flex flex-col items-start rounded-lg border border-zinc-800 bg-zinc-900/60 p-2 text-left hover:border-blue-500/50 hover:bg-zinc-800/80 transition-all"
                  >
                    <span className="text-[11px] font-bold text-zinc-200">{r.role}</span>
                    <span className="text-[10px] text-zinc-500">{r.email}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
