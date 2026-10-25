// 職缺來源代碼 → 顯示名稱（與 JobList 元件分開，避免 react-refresh 對「同檔混合匯出」告警）。
export const SRC_LABEL: Record<string, string> = {
  "104": "104", yourator: "Yourator", linkedin: "LinkedIn", cake: "Cake", careers: "官網", sample: "範例",
  web3career: "web3.career", cryptojobslist: "CryptoJobsList",
  dejob: "DeJob", jobfrog: "JobFrog",
  cryptocurrencyjobs: "CryptocurrencyJobs", defijobs: "DeFi Jobs",
}

export const WORK_MODE_LABEL: Record<string, string> = {
  onsite: "現場辦公", hybrid: "部分遠端", remote: "全遠端",
}

// 可搜尋來源（供使用者勾選；排除 careers/sample 這類展示用非搜尋來源）。
export const SOURCES: { key: string; label: string }[] = [
  "104", "yourator", "linkedin", "cake", "web3career", "cryptojobslist",
  "dejob", "jobfrog", "cryptocurrencyjobs", "defijobs",
].map((key) => ({ key, label: SRC_LABEL[key] }))
