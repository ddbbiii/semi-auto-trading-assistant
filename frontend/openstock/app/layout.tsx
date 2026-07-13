import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "投资决策台",
  description: "个人持仓、风险与机会决策工作台。",
};

export default function RootLayout({
                                       children,
                                   }: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="zh-CN">
            <body>{children}</body>
        </html>
    );
}
