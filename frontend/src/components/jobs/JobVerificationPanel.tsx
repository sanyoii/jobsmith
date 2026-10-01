import { useEffect, useRef, useState } from "react"
import type { FormEvent } from "react"
import type { RemoteEligibility } from "../../types"

const LABELS: Record<string, string> = {
  taiwan_eligibility: "台灣聘僱", work_mode: "工作方式", schedule: "輪班／待命",
  salary: "薪資", employment_type: "聘僱形式",
}
interface Check {
  criterion: string; requirement: string; value: string; evidence: string; source_url: string
  checked_at: string | null; expired?: boolean
}
interface Verification { summary: string; checks: Check[] }
interface EvidencePackage {
  id: number; job_url?: string | null; outcome_status?: string | null; outcome_note?: string | null
  current_event_id?: string | null; evidence_status?: string
}
interface ApplicationEvent {
  event_id: string; status: string | null; occurred_at: string
  evidence_text: string; reference?: string; source_url?: string; confirmed_by_user: boolean
  correction_reason?: string
}
const STATUS_LABELS: Record<string, string> = {
  applied: "已投遞", interviewing: "面試邀約", offer: "Offer", rejected: "未錄取", ghosted: "無回音",
}
const KIND_LABELS: Record<string, string> = {
  success_page: "成功頁", application_reference: "申請編號", confirmation_email: "確認信",
  portal: "網站結果", email: "通知信", manual: "本人紀錄",
}
const field = "block w-full rounded border border-slate-300 p-2 text-sm"
function localTime(iso?: string | null) {
  const d = iso ? new Date(iso) : new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
function isoTime(value: string) {
  if (!value || !Number.isFinite(Date.parse(value))) throw new Error("請填有效的時間")
  return new Date(value).toISOString()
}
function safeHref(value?: string | null) {
  try {
    if (!value || /[\s\\]/.test(value)) return undefined
    const u = new URL(value)
    return u.protocol === "https:" && !u.username && !u.password ? u.href : undefined
  } catch { return undefined }
}
async function api(path: string, init?: RequestInit) {
  const response = await fetch(path, init)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || (response.status === 422 ? "請確認欄位與時間是否完整" : "保存或讀取失敗，請稍後再試"))
  return data
}
function jsonBody(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
}
function emptyCheck(criterion: string): Check {
  return { criterion, requirement: "", value: "unknown", evidence: "", source_url: "", checked_at: null }
}

export function RemoteEligibilityPanel({ assessment }: { assessment?: RemoteEligibility | null }) {
  const labels = { pass: "符合", fail: "不符合", unknown: "待確認" }
  return <section className="mt-3 text-sm rounded-lg bg-slate-50 p-3" aria-label="全遠端與台灣工作初查">
    <p className="font-medium">全遠端：{labels[assessment?.remote.value || "unknown"]}｜台灣工作：{labels[assessment?.taiwan.value || "unknown"]}</p>
    {!assessment && <p className="text-xs text-slate-500 mt-1">尚未自動初查；重新搜尋並啟用台灣全遠端條件。</p>}
    {assessment && <>
      {assessment.remote.value !== "pass" && <p className="mt-1">{assessment.remote.reason}</p>}
      <p className="mt-1">{assessment.taiwan.reason}</p>
      <details className="mt-1"><summary>查看判斷依據</summary>
        <p className="text-xs text-slate-500">{assessment.method === "page" ? "職缺內頁自動初查" : assessment.method === "unavailable" ? "內頁無法讀取" : "尚未讀取內頁"}；不代表已確認聘僱法律或合約安排。</p>
        {[...new Set([...assessment.remote.evidence, ...assessment.taiwan.evidence])].map((line, i) => <blockquote key={i} className="border-l-2 border-slate-300 pl-2 mt-1 break-words">{line}</blockquote>)}
        {safeHref(assessment.source_url) && <a className="underline" href={safeHref(assessment.source_url)} target="_blank" rel="noreferrer noopener">查看初查來源</a>}
        {assessment.checked_at && <p className="text-xs text-slate-500">{new Date(assessment.checked_at).toLocaleString("zh-TW")}</p>}
      </details>
    </>}
  </section>
}

export function JobVerificationPanel({ jobUrl }: { jobUrl: string }) {
  const [data, setData] = useState<Verification | null>(null)
  const [error, setError] = useState("")
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const saving = useRef(false)
  const [draft, setDraft] = useState<Check>(emptyCheck("taiwan_eligibility"))
  const [time, setTime] = useState("")
  useEffect(() => {
    let live = true
    api("/api/job-verifications/query", jsonBody("POST", { job_urls: [jobUrl] }))
      .then((result) => { if (live) { setData(Object.values(result.jobs)[0] as Verification); setError("") } })
      .catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [jobUrl])
  function select(criterion: string) {
    const previous = data?.checks.find((c) => c.criterion === criterion)
    setDraft(previous || emptyCheck(criterion))
    setTime(previous?.checked_at ? localTime(previous.checked_at) : "")
  }
  async function save(e: FormEvent) {
    e.preventDefault()
    if (saving.current) return
    saving.current = true; setBusy(true); setError("")
    try {
      const check = {
        criterion: draft.criterion, requirement: draft.requirement, value: draft.value,
        evidence: draft.evidence, source_url: draft.source_url, checked_at: time ? isoTime(time) : null,
      }
      setData(await api("/api/job-verifications", jsonBody("PUT", { job_url: jobUrl, check })))
      setEditing(false)
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗") }
    finally { saving.current = false; setBusy(false) }
  }
  return <section className="mt-3 text-sm" aria-label="求職條件查證">
    <p>{data ? "目前查證：" + data.summary : error ? "查證資料讀取失敗" : "正在讀取查證資料…"}</p>
    {error && <p role="alert" className="text-rose-700">{error}</p>}
    <button type="button" className="text-brand-700 underline mt-1"
      onClick={() => { select(draft.criterion); setEditing(!editing) }}>記錄查證</button>
    <details className="mt-1"><summary>查看五項條件與依據</summary>
      {Object.entries(LABELS).map(([key, label]) => {
        const check = data?.checks.find((c) => c.criterion === key)
        return <div key={key} className="border-t py-2">
          <p>{label}：{check ? (check.expired ? "查證已過期" : check.value === "pass" ? "符合" : check.value === "fail" ? "不符合" : "待確認") : "待確認"}</p>
          {check && <><p>要求：{check.requirement}</p><p>{check.evidence}</p>
            {safeHref(check.source_url) && <a href={safeHref(check.source_url)} target="_blank" rel="noreferrer noopener" className="underline">查看來源</a>}
            <p>{check.checked_at ? new Date(check.checked_at).toLocaleString("zh-TW") : "尚無查證時間"}</p></>}
        </div>
      })}
    </details>
    {editing && <form onSubmit={save} className="space-y-2 mt-2">
      <label className="block">條件<select className={field} value={draft.criterion} onChange={(e) => select(e.target.value)}>
        {Object.entries(LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="block">希望的條件<input className={field} value={draft.requirement} required maxLength={500}
        onChange={(e) => setDraft({ ...draft, requirement: e.target.value })} /></label>
      <label className="block">判斷<select className={field} value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })}>
        <option value="unknown">待確認</option><option value="pass">符合</option><option value="fail">不符合</option></select></label>
      <label className="block">依據原文或摘要<textarea className={field} value={draft.evidence} maxLength={3000} required={draft.value !== "unknown"}
        onChange={(e) => setDraft({ ...draft, evidence: e.target.value })} /></label>
      <label className="block">來源 HTTPS 網址<input className={field} value={draft.source_url} type="url" maxLength={2048} required={draft.value !== "unknown"}
        onChange={(e) => setDraft({ ...draft, source_url: e.target.value })} /></label>
      <label className="block">查證時間（本機時區）<input className={field} type="datetime-local" value={time}
        required={draft.value !== "unknown"} onChange={(e) => setTime(e.target.value)} /></label>
      <button className="rounded bg-brand-600 text-white px-3 py-2" disabled={busy}>{busy ? "保存中…" : "保存查證"}</button>
    </form>}
    <p className="text-xs text-slate-500 mt-1">依本人記錄的要求判斷；超過七天提醒重新查證，不代表整體適任。</p>
  </section>
}

export function ApplicationEvidencePanel({ pkg, onSaved }: { pkg: EvidencePackage; onSaved: () => Promise<void> }) {
  const [source, setSource] = useState(pkg.job_url || "")
  const [status, setStatus] = useState(pkg.outcome_status || "")
  const [note, setNote] = useState(pkg.outcome_note || "")
  const [kind, setKind] = useState(pkg.outcome_status === "applied" ? "application_reference" : "manual")
  const [text, setText] = useState("")
  const [reference, setReference] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [time, setTime] = useState(localTime())
  const [confirmed, setConfirmed] = useState(false)
  const [correction, setCorrection] = useState(false)
  const [reason, setReason] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const saving = useRef(false)
  const retry = useRef<{ key: string; payload: string } | null>(null)
  const [events, setEvents] = useState<ApplicationEvent[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [eventError, setEventError] = useState("")
  useEffect(() => {
    let live = true
    api("/api/history/" + pkg.id + "/events")
      .then((data) => { if (live) { setEvents(data.events); setCursor(data.next_cursor); setEventError("") } })
      .catch((e: Error) => { if (live) setEventError(e.message) })
    return () => { live = false }
  }, [pkg.id, pkg.current_event_id])
  async function more() {
    try {
      const data = await api("/api/history/" + pkg.id + "/events?cursor=" + cursor)
      setEvents((old) => [...old, ...data.events]); setCursor(data.next_cursor); setEventError("")
    } catch (e) { setEventError(e instanceof Error ? e.message : "讀取失敗") }
  }
  async function saveSource() {
    if (saving.current) return
    saving.current = true; setBusy(true); setError("")
    try {
      await api("/api/history/" + pkg.id + "/job-source", jsonBody("PATCH", { job_url: source || null }))
      await onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗") }
    finally { saving.current = false; setBusy(false) }
  }
  async function save(e: FormEvent) {
    e.preventDefault()
    if (saving.current) return
    saving.current = true; setBusy(true); setError("")
    try {
      const payload = {
        status: status || null, note, occurred_at: isoTime(time), expected_event_id: pkg.current_event_id ?? null,
        evidence: { evidence_kind: kind, evidence_text: text, source_url: sourceUrl || null, reference: reference || null, confirmed_by_user: confirmed },
        correction: correction || !status, correction_reason: reason,
      }
      const serialized = JSON.stringify(payload)
      if (!retry.current || retry.current.payload !== serialized) retry.current = { payload: serialized, key: crypto.randomUUID() }
      await api("/api/history/" + pkg.id + "/outcome", jsonBody("PATCH", { ...payload, idempotency_key: retry.current.key }))
      await onSaved()
      retry.current = null; setConfirmed(false)
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗") }
    finally { saving.current = false; setBusy(false) }
  }
  const evidenceLabel = pkg.evidence_status === "user_confirmed" ? "本人已確認憑證；系統未自動驗真"
    : pkg.evidence_status === "unverified" ? "人工紀錄，憑證未確認" : "舊紀錄，憑證未核對"
  return <section className="no-print rounded border p-4 mb-4 space-y-3" aria-label="投遞結果與憑證">
    <p>目前結果：{STATUS_LABELS[pkg.outcome_status || ""] || "未投遞"}。{evidenceLabel}</p>
    <label className="block">職缺來源 HTTPS 網址<input className={field} type="url" value={source} maxLength={2048} onChange={(e) => setSource(e.target.value)} /></label>
    <button type="button" className="text-brand-700 underline" disabled={busy} onClick={saveSource}>保存職缺來源</button>
    {pkg.job_url ? <JobVerificationPanel key={pkg.job_url} jobUrl={pkg.job_url} /> : <p>未連結職缺來源</p>}
    {error && <p role="alert" className="text-rose-700">{error}<button type="button" className="underline ml-2"
      onClick={() => void onSaved().catch(() => setError("重新讀取失敗"))}>重新讀取目前結果</button></p>}
    <form onSubmit={save} className="space-y-2">
      <label className="block">要記錄的結果<select className={field} value={status} onChange={(e) => {
        setStatus(e.target.value); setKind(e.target.value === "applied" ? "application_reference" : "manual")
      }}><option value="">未投遞（更正）</option>
        {Object.entries(STATUS_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="block">憑證種類<select className={field} value={kind} onChange={(e) => setKind(e.target.value)}>
        {(status === "applied" ? ["success_page", "application_reference", "confirmation_email"]
          : status === "ghosted" || !status ? ["manual"] : ["portal", "email", "manual"])
          .map((key) => <option key={key} value={key}>{KIND_LABELS[key]}</option>)}</select></label>
      <label className="block">憑證摘要<textarea className={field} value={text} required maxLength={3000} onChange={(e) => setText(e.target.value)} /></label>
      <label className="block">申請編號<input className={field} value={reference} maxLength={200}
        required={kind === "application_reference"} onChange={(e) => setReference(e.target.value)} /></label>
      <label className="block">憑證 HTTPS 網址（可空）<input className={field} type="url" value={sourceUrl} maxLength={2048} onChange={(e) => setSourceUrl(e.target.value)} /></label>
      <label className="block">事件時間（本機時區）<input className={field} type="datetime-local" value={time} required onChange={(e) => setTime(e.target.value)} /></label>
      <label className="block">備註<textarea className={field} value={note} maxLength={3000} onChange={(e) => setNote(e.target.value)} /></label>
      <label className="block"><input type="checkbox" checked={correction} onChange={(e) => setCorrection(e.target.checked)} /> 更正已記錄的結果</label>
      {(correction || !status) && <label className="block">更正原因<input className={field} value={reason} required maxLength={3000} onChange={(e) => setReason(e.target.value)} /></label>}
      <label className="block"><input type="checkbox" checked={confirmed} required onChange={(e) => setConfirmed(e.target.checked)} /> 我已核對這份憑證與結果</label>
      <p className="text-xs text-slate-500">只填必要摘要；不要貼完整郵件、帳密或登入資料。核可文件不等於已投遞。</p>
      <button className="rounded bg-brand-600 text-white px-3 py-2" disabled={busy}>{busy ? "保存中…" : "保存結果與憑證"}</button>
    </form>
    <details><summary>查看投遞事件紀錄（{events.length}）</summary>
      {eventError && <p role="alert">{eventError}</p>}
      {events.map((event) => <article key={event.event_id} className="border-t py-2">
        <p>{STATUS_LABELS[event.status || ""] || "未投遞"} · {new Date(event.occurred_at).toLocaleString("zh-TW")}</p>
        <p>{event.confirmed_by_user ? "本人已確認" : "未確認憑證"} · {event.evidence_text}</p>
        {event.reference && <p>申請編號：{event.reference}</p>}
        {safeHref(event.source_url) && <a href={safeHref(event.source_url)} target="_blank" rel="noreferrer noopener" className="underline">查看憑證來源</a>}
        {event.correction_reason && <p>更正原因：{event.correction_reason}</p>}
      </article>)}
      {cursor !== null && <button type="button" className="underline" onClick={more}>載入更多紀錄</button>}
    </details>
  </section>
}
