"use client";

import { ChangeEvent, DragEvent, FormEvent, KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, FileCheck2, FileUp, Plus, Trash2, X } from "lucide-react";
import { apiBase } from "@/lib/decision-api";

type Market = "US" | "HK" | "CN";
type Currency = "USD" | "HKD" | "CNY";
type HoldingRow = {
    symbol: string;
    name: string;
    market: Market;
    security_type: string;
    quantity: number;
    available_quantity?: number | null;
    currency: Currency;
    market_value: number;
    price: number;
    average_cost: number;
    theme: string;
    holding_pnl?: number | null;
    holding_pnl_percent?: number | null;
};
type Preview = {
    import_id: string;
    file_name: string;
    parser: string;
    account: Record<string, unknown>;
    warnings: string[];
    holdings: HoldingRow[];
};

const emptyRow = (): HoldingRow => ({
    symbol: "", name: "", market: "US", security_type: "stock", quantity: 0,
    currency: "USD", market_value: 0, price: 0, average_cost: 0, theme: "",
});

const acceptedExtensions = new Set(["png", "jpg", "jpeg", "webp", "csv", "xlsx"]);
const imageExtensions = new Set(["png", "jpg", "jpeg", "webp"]);
const maxUploadBytes = 10 * 1024 * 1024;
const maxScreenshotCount = 8;
const parserLabels: Record<string, string> = {
    vision_model: "视觉模型",
    multi_image_ocr: "本地 OCR",
    png: "本地 OCR",
    jpg: "本地 OCR",
    jpeg: "本地 OCR",
    webp: "本地 OCR",
    csv: "CSV",
    xlsx: "XLSX",
};

function formatFileSize(bytes: number) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function DataImportDialog() {
    const [open, setOpen] = useState(false);
    const [preview, setPreview] = useState<Preview | null>(null);
    const [rows, setRows] = useState<HoldingRow[]>([]);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState("");
    const [accountName, setAccountName] = useState("主账户");
    const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
    const [dragActive, setDragActive] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (!open) return;
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        const closeOnEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") setOpen(false);
        };
        window.addEventListener("keydown", closeOnEscape);
        return () => {
            document.body.style.overflow = previousOverflow;
            window.removeEventListener("keydown", closeOnEscape);
        };
    }, [open]);

    const previewFile = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (selectedFiles.length === 0) {
            setMessage("请先拖入文件，或点击上传区域选择文件。");
            return;
        }
        const form = new FormData();
        selectedFiles.forEach((file) => form.append("files", file, file.name));
        setBusy(true);
        setMessage("");
        try {
            const response = await fetch(`${apiBase}/api/v1/import/preview`, { method: "POST", body: form });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || "导入预览失败");
            setPreview(payload);
            setRows(payload.holdings);
        } catch (error) {
            setMessage(error instanceof Error ? error.message : "导入预览失败");
        } finally {
            setBusy(false);
        }
    };

    const selectFiles = (incoming: File[]) => {
        if (incoming.length === 0) return;
        const invalid = incoming.find((file) => !acceptedExtensions.has(file.name.split(".").pop()?.toLowerCase() || ""));
        if (invalid) {
            setMessage(`${invalid.name} 的格式不受支持。请上传 PNG、JPG、WEBP、CSV 或 XLSX。`);
            return;
        }
        const oversized = incoming.find((file) => file.size > maxUploadBytes);
        if (oversized) {
            setMessage(`${oversized.name} 超过 10 MB，请压缩后重试。`);
            return;
        }

        const combined = [...selectedFiles, ...incoming].filter((file, index, all) =>
            all.findIndex((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified) === index,
        );
        const extensions = combined.map((file) => file.name.split(".").pop()?.toLowerCase() || "");
        if (combined.length > 1 && extensions.some((extension) => !imageExtensions.has(extension))) {
            setMessage("多文件导入只支持截图；CSV 或 XLSX 请单独上传。");
            return;
        }
        if (combined.length > maxScreenshotCount) {
            setMessage(`一次最多选择 ${maxScreenshotCount} 张截图。`);
            return;
        }

        setSelectedFiles(combined);
        setPreview(null);
        setRows([]);
        setMessage("");
    };

    const dropFile = (event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setDragActive(false);
        selectFiles(Array.from(event.dataTransfer.files));
    };

    const openFilePicker = () => {
        if (!busy) fileInputRef.current?.click();
    };

    const openFilePickerWithKeyboard = (event: ReactKeyboardEvent<HTMLDivElement>) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openFilePicker();
        }
    };

    const updateRow = (index: number, field: keyof HoldingRow, value: string) => {
        setRows((current) => current.map((row, rowIndex) => {
            if (rowIndex !== index) return row;
            if (["quantity", "market_value", "price", "average_cost"].includes(field)) {
                return { ...row, [field]: Number(value) || 0 };
            }
            return { ...row, [field]: value };
        }));
    };

    const commit = async () => {
        if (rows.some((row) => !row.symbol.trim() || row.quantity < 0 || row.market_value < 0)) {
            setMessage("请补齐代码，并检查数量与市值不能为负数。");
            return;
        }
        setBusy(true);
        setMessage("");
        try {
            const response = await fetch(`${apiBase}/api/v1/import/commit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    import_id: preview?.import_id,
                    source: `confirmed_${preview?.parser || "manual"}`,
                    as_of: new Date().toISOString(),
                    account: { ...(preview?.account || {}), name: accountName },
                    holdings: rows,
                    pending_order_count: 0,
                }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || "确认入库失败");
            setMessage(`已同步 ${rows.length} 条持仓，正在刷新决策。`);
            setTimeout(() => window.location.reload(), 500);
        } catch (error) {
            setMessage(error instanceof Error ? error.message : "确认入库失败");
        } finally {
            setBusy(false);
        }
    };

    const openDialog = () => {
        setPreview(null);
        setRows([]);
        setMessage("");
        setSelectedFiles([]);
        setDragActive(false);
        setOpen(true);
    };

    const dialog = open ? createPortal(
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setOpen(false)}>
            <section className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="account-sync-title" onMouseDown={(event) => event.stopPropagation()}>
                <div className="dialog-heading"><div><p className="eyebrow">ACCOUNT SYNC</p><h2 id="account-sync-title">导入账户快照</h2></div><button type="button" aria-label="关闭" autoFocus onClick={() => setOpen(false)}><X /></button></div>
                <p className="dialog-copy">支持券商截图、CSV 和 XLSX。截图经压缩后发送至已配置的视觉模型，仅用于生成确认表；不会自动同步，也不保存原图。</p>
                <form onSubmit={previewFile} className="upload-form">
                    <div
                        className={`file-dropzone${dragActive ? " drag-active" : ""}${selectedFiles.length ? " has-file" : ""}`}
                        role="button"
                        tabIndex={0}
                        aria-label="拖入一张或多张账户截图，也可点击选择文件"
                        onClick={openFilePicker}
                        onKeyDown={openFilePickerWithKeyboard}
                        onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }}
                        onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setDragActive(true); }}
                        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragActive(false); }}
                        onDrop={dropFile}
                    >
                        <input ref={fileInputRef} type="file" multiple accept=".png,.jpg,.jpeg,.webp,.csv,.xlsx" onChange={(event) => { selectFiles(Array.from(event.target.files || [])); event.target.value = ""; }} />
                        <span className="dropzone-icon">{selectedFiles.length ? <FileCheck2 /> : <FileUp />}</span>
                        <span className="dropzone-copy">
                            <strong>{selectedFiles.length > 1 ? `已选择 ${selectedFiles.length} 张账户截图` : selectedFiles[0]?.name || (dragActive ? "松开即可添加文件" : "拖拽一张或多张截图到这里")}</strong>
                            <small>{selectedFiles.length ? `${formatFileSize(selectedFiles.reduce((total, file) => total + file.size, 0))} · 点击可继续添加` : "也可以点击选择 · 最多 8 张截图，或单个 CSV / XLSX"}</small>
                        </span>
                    </div>
                    {selectedFiles.length ? <div className="selected-files" aria-label="已选择文件">
                        {selectedFiles.map((file) => <span key={`${file.name}-${file.size}-${file.lastModified}`}><span><strong>{file.name}</strong><small>{formatFileSize(file.size)}</small></span><button type="button" aria-label={`移除 ${file.name}`} onClick={() => { setSelectedFiles((current) => current.filter((item) => item !== file)); setPreview(null); setRows([]); }}><X /></button></span>)}
                    </div> : null}
                    <button className="primary-button upload-submit" disabled={busy || selectedFiles.length === 0}>{busy ? `正在识别 ${selectedFiles.length} 个文件…` : selectedFiles.length > 1 ? `识别 ${selectedFiles.length} 张截图` : "生成确认表"}</button>
                </form>
                {message ? <p className={message.startsWith("已同步") ? "success-banner" : "error-banner"}>{message}</p> : null}
                {preview ? <div className="preview-panel">
                    <div className="preview-summary"><strong>{rows.length}</strong><span>条待确认持仓</span><small>{preview.file_name} · {parserLabels[preview.parser] || preview.parser}</small></div>
                    {preview.warnings.map((warning) => <p key={warning} className="warning-line">{warning}</p>)}
                    <label className="account-field"><span>账户名称</span><input value={accountName} onChange={(event) => setAccountName(event.target.value)} /></label>
                    <div className="preview-table"><table><thead><tr><th>代码 / 名称</th><th>市场 / 币种</th><th>数量</th><th>市值</th><th>现价</th><th>成本</th><th></th></tr></thead><tbody>
                        {rows.map((row, index) => <tr key={`${index}-${row.symbol}`}>
                            <td><input aria-label={`第 ${index + 1} 行代码`} value={row.symbol} onChange={(event) => updateRow(index, "symbol", event.target.value.toUpperCase())} /><input aria-label={`第 ${index + 1} 行名称`} value={row.name} placeholder="名称" onChange={(event) => updateRow(index, "name", event.target.value)} /></td>
                            <td><select value={row.market} onChange={(event: ChangeEvent<HTMLSelectElement>) => updateRow(index, "market", event.target.value)}><option value="US">美股</option><option value="HK">港股</option><option value="CN">A 股</option></select><select value={row.currency} onChange={(event) => updateRow(index, "currency", event.target.value)}><option>USD</option><option>HKD</option><option>CNY</option></select></td>
                            {(["quantity", "market_value", "price", "average_cost"] as const).map((field) => <td key={field}><input type="number" min="0" step="any" value={row[field]} onChange={(event) => updateRow(index, field, event.target.value)} /></td>)}
                            <td><button className="icon-button danger" type="button" aria-label={`删除 ${row.symbol || `第 ${index + 1} 行`}`} onClick={() => setRows((current) => current.filter((_, rowIndex) => rowIndex !== index))}><Trash2 /></button></td>
                        </tr>)}
                    </tbody></table></div>
                    <div className="preview-actions"><button className="secondary-button" type="button" onClick={() => setRows((current) => [...current, emptyRow()])}><Plus />添加一行</button><button className="primary-button" type="button" disabled={busy || rows.length === 0} onClick={commit}><Check />确认并更新决策</button></div>
                    <p className="muted-note">确认会把这份快照设为当前持仓并重新计算决策；系统不会自动下单。</p>
                </div> : null}
            </section>
        </div>,
        document.body,
    ) : null;

    return <>
        <button className="import-trigger" type="button" onClick={openDialog}><FileUp size={16} />同步账户</button>
        {dialog}
    </>;
}
