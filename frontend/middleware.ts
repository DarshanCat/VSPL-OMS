import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  const token = req.cookies.get("access_token");
  const isAuthPage = req.nextUrl.pathname.startsWith("/login");
  const isTrainingPage = req.nextUrl.pathname.startsWith("/training");

  if (!token && !isAuthPage && !isTrainingPage) {
    return NextResponse.redirect(new URL("/login", req.url));
  }

  return NextResponse.next();
}

export const config = {
  runtime: "nodejs",
  matcher: [
    "/((?!api|health|_next/static|_next/image|favicon.ico).*)",
  ],
};
