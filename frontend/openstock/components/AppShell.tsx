"use client";

import { BarChart3, BriefcaseBusiness, CircleDollarSign, DatabaseZap, Settings2 } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import DataImportDialog from "@/components/DataImportDialog";

const nav = [
    { href: "/", label: "决策", icon: BarChart3 },
    { href: "/holdings", label: "持仓", icon: BriefcaseBusiness },
    { href: "/opportunities", label: "机会", icon: CircleDollarSign },
    { href: "/settings", label: "设置", icon: Settings2 },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
    const pathname = usePathname();
    return (
        <main className="app-frame">
            <header className="topbar">
                <Link href="/" className="brand" aria-label="投资决策台首页">
                    <span className="brand-mark"><DatabaseZap size={19} /></span>
                    <span><strong>决策台</strong><small>Personal investment desk</small></span>
                </Link>
                <nav className="main-nav" aria-label="主导航">
                    {nav.map(({ href, label, icon: Icon }) => {
                        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                        return <Link key={href} href={href} className={active ? "active" : ""}><Icon size={17} />{label}</Link>;
                    })}
                </nav>
                <DataImportDialog />
            </header>
            <div className="workspace">{children}</div>
            <footer className="legal-note">
                决策结果仅用于个人研究与复核，不构成自动交易指令。界面基于 OpenStock 改造，保留原项目许可与归属。
            </footer>
        </main>
    );
}
