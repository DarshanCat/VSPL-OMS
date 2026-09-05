#!/bin/bash
set -e

echo "Creating VSPL SMES frontend structure..."

npx create-next-app@15 frontend --typescript --tailwind --app --no-src-dir --eslint --import-alias "@/*" --use-npm
cd frontend

npm install @tanstack/react-query @tanstack/react-table react-hook-form zod @hookform/resolvers recharts framer-motion axios js-cookie
npm install -D @types/js-cookie

mkdir -p lib
mkdir -p "app/(auth)/login"

# ---------- lib/api.ts ----------
cat > lib/api.ts << 'EOF'
import axios from "axios";
import Cookies from "js-cookie";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

api.interceptors.request.use((config) => {
  const token = Cookies.get("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export async function login(email: string, password: string) {
  const { data } = await api.post("/api/v1/auth/login", { email, password });
  Cookies.set("access_token", data.access_token, { expires: 1 });
  return data;
}
EOF

# ---------- middleware.ts ----------
cat > middleware.ts << 'EOF'
import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  const token = req.cookies.get("access_token");
  const isAuthPage = req.nextUrl.pathname.startsWith("/login");

  if (!token && !isAuthPage) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
EOF

# ---------- app/(auth)/login/page.tsx ----------
cat > "app/(auth)/login/page.tsx" << 'EOF'
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch {
      setError("Invalid email or password");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-sm rounded-xl bg-white dark:bg-gray-800 p-8 shadow-lg">
        <h1 className="mb-6 text-xl font-semibold">VSPL SMES Login</h1>
        <div className="space-y-4">
          <input
            className="w-full rounded-lg border px-3 py-2"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            className="w-full rounded-lg border px-3 py-2"
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            onClick={handleSubmit}
            className="w-full rounded-lg bg-brand-500 py-2 font-medium text-white hover:bg-brand-700"
          >
            Sign in
          </button>
        </div>
      </div>
    </div>
  );
}
EOF

# ---------- .env.local ----------
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF

echo "Frontend files created."
echo "Next steps:"
echo "  cd frontend"
echo "  npm run dev"