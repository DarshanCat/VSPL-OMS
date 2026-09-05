import "./globals.css";

export const metadata = {
  title: "VSPL SMES",
  description: "AI Powered Production Tracking, Planning & Manufacturing Intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
        {children}
      </body>
    </html>
  );
}