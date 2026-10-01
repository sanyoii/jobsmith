import { useState } from "react"
import { JobVerificationPanel, RemoteEligibilityPanel } from "./JobVerificationPanel"
import type { JobMatch, JobPosting } from "../../types"
import { SRC_LABEL, WORK_MODE_LABEL } from "../../lib/sources"
import { Card } from "../../ui/Card"
import { Button } from "../../ui/Button"
import { Badge } from "../../ui/Badge"
import { Sparkles, ExternalLink, ChevronLeft, ChevronRight } from "../../ui/icons"

const PAGE_SIZE = 8

// 適配以高/中/低色帶呈現（內部仍用 fit_score 排序/篩選）；避免與投遞包的「匹配評分」數字打架。
function fitBand(s: number) {
  return s >= 80 ? { label: "高", cls: "from-emerald-500 to-emerald-600" }
    : s >= 60 ? { label: "中", cls: "from-amber-500 to-amber-600" }
      : { label: "低", cls: "from-slate-400 to-slate-500" }
}

function FitBadge({ score }: { score: number }) {
  const b = fitBand(score)
  return (
    <div className={`shrink-0 w-14 h-14 rounded-xl bg-gradient-to-br ${b.cls} text-white grid place-items-center text-center`}>
      <div className="text-xl font-bold leading-none">{b.label}</div>
      <div className="text-[9px] opacity-85 mt-0.5">適配</div>
    </div>
  )
}

function JobCard({ m, onPick, pending }: { m: JobMatch; onPick: (m: JobMatch) => void; pending?: boolean }) {
  return (
    <Card interactive className="p-4 flex flex-col sm:flex-row gap-4 animate-fade-in-up">
      <FitBadge score={m.fit_score} />
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <a href={m.job.url} target="_blank" rel="noreferrer"
            className="font-medium text-slate-900 hover:text-brand-700 hover:underline rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">{m.job.title}</a>
          <Badge tone={m.job.source === "careers" ? "brand" : "slate"}>{SRC_LABEL[m.job.source] || m.job.source}</Badge>
          {m.job.work_mode && <Badge tone="slate">{WORK_MODE_LABEL[m.job.work_mode]}</Badge>}
        </div>
        <p className="text-sm text-slate-600 mt-0.5">
          {m.job.company}
          {m.job.location ? `｜${m.job.location}` : ""}
          {m.job.salary ? `｜${m.job.salary}` : ""}
        </p>
        {m.reason && <p className="text-sm text-slate-700 mt-1">{m.reason}</p>}
        {m.matched.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {m.matched.map((t, k) => <Badge key={k} tone="emerald">{t}</Badge>)}
          </div>
        )}
        <RemoteEligibilityPanel assessment={m.job.remote_eligibility} />
        <details className="mt-2 text-sm"><summary>其他條件與手動紀錄（選填）</summary>
          <JobVerificationPanel key={m.job.url} jobUrl={m.job.url} />
        </details>
      </div>
      <div className="shrink-0 flex flex-row sm:flex-col gap-2">
        <Button size="sm" icon={Sparkles} loading={pending} onClick={() => onPick(m)} className="whitespace-nowrap">產生投遞包</Button>
        <a href={m.job.url} target="_blank" rel="noreferrer"
          className="inline-flex items-center justify-center gap-1 px-3 py-1.5 bg-slate-100 text-slate-600 rounded-lg text-sm hover:bg-slate-200 transition whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">
          <ExternalLink className="w-3.5 h-3.5" />看原職缺
        </a>
      </div>
    </Card>
  )
}

// 可分頁的職缺清單；onPick 可為 async（抓完整 JD 時該卡按鈕顯示載入中）。
function PagedJobList({ matches, onPick }:
  { matches: JobMatch[]; onPick: (m: JobMatch) => void | Promise<void> }) {
  const [page, setPage] = useState(1)
  const [pendingUrl, setPendingUrl] = useState("")
  // 新一輪結果（matches 參考改變）→ 在 render 期回到第 1 頁（React 官方「prop 改變時
  // 調整 state」做法：用 state 記錄上一批比對，免 effect、不讀寫 ref）。
  const [prevMatches, setPrevMatches] = useState(matches)
  if (prevMatches !== matches) {
    setPrevMatches(matches)
    setPage(1)
  }
  const totalPages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE))
  const cur = Math.min(page, totalPages)

  async function handle(m: JobMatch) {
    if (pendingUrl) return  // 已有一張卡在抓 JD/開跑 → 忽略連點，避免同時觸發多條 pipeline
    setPendingUrl(m.job.url)
    try { await onPick(m) } finally { setPendingUrl("") }
  }

  return (
    <>
      <div className="space-y-3">
        {matches.slice((cur - 1) * PAGE_SIZE, cur * PAGE_SIZE).map((m, i) => (
          <JobCard key={i} m={m} onPick={handle} pending={!!pendingUrl && m.job.url === pendingUrl} />
        ))}
      </div>
      {matches.length > PAGE_SIZE && (
        <nav aria-label="職缺分頁" className="flex items-center justify-center gap-1.5 mt-5">
          <Button variant="secondary" size="sm" icon={ChevronLeft}
            disabled={cur <= 1} onClick={() => setPage(Math.max(1, cur - 1))}>上一頁</Button>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
            <button key={n} onClick={() => setPage(n)} aria-current={n === cur ? "page" : undefined}
              className={`w-8 h-8 rounded-lg text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 ${
                n === cur ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}>{n}</button>
          ))}
          <Button variant="secondary" size="sm" onClick={() => setPage(Math.min(totalPages, cur + 1))}
            disabled={cur >= totalPages}>下一頁<ChevronRight className="w-4 h-4" /></Button>
        </nav>
      )}
    </>
  )
}


export function JobList({ matches, onPick }: { matches: JobMatch[]; onPick: (m: JobMatch) => void | Promise<void> }) {
  if (!matches.some((m) => m.job.remote_eligibility)) return <PagedJobList matches={matches} onPick={onPick} />
  const confirmed = matches.filter((m) => m.job.remote_eligibility?.status === "pass")
  const pending = matches.filter((m) => !m.job.remote_eligibility || m.job.remote_eligibility.status === "unknown")
  return <>
    {confirmed.length > 0 && <><h3 className="font-semibold mb-3">全遠端、接受台灣工作地區（{confirmed.length}）</h3><PagedJobList matches={confirmed} onPick={onPick} /></>}
    {pending.length > 0 && <div className="mt-5"><h3 className="font-semibold mb-2">台灣全遠端條件待確認（{pending.length}）</h3>
      <p className="text-sm text-slate-500 mb-3">資訊不足或尚未完成初查的職缺保留在這裡。</p><PagedJobList matches={pending} onPick={onPick} /></div>}
  </>
}

export function ExcludedRemoteJobs({ jobs }: { jobs: JobPosting[] }) {
  if (!jobs.length) return null
  return <details className="mt-5 rounded-xl border border-slate-200 p-4">
    <summary className="font-medium">已排除：不符合台灣全遠端條件（{jobs.length}）</summary>
    <div className="space-y-3 mt-3">{jobs.map((job) => <article key={job.url} className="border-t pt-3">
      <a href={job.url} target="_blank" rel="noreferrer noopener" className="underline font-medium">{job.title} · {job.company}</a>
      <RemoteEligibilityPanel assessment={job.remote_eligibility} />
    </article>)}</div>
  </details>
}
