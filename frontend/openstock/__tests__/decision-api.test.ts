import { describe, expect, it } from "vitest";
import { formatMoney, relativeTime } from "@/lib/decision-api";

describe("decision desk formatting", () => {
    it("formats original currencies without silently converting them", () => {
        expect(formatMoney(100, "USD")).toContain("100.00");
        expect(formatMoney(100, "CNY")).toContain("100.00");
    });

    it("makes stale timestamps visible", () => {
        const value = new Date(Date.now() - 26 * 60 * 60 * 1000).toISOString();
        expect(relativeTime(value)).toMatch(/天前/);
    });
});
