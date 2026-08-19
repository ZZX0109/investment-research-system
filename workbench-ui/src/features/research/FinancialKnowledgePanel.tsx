import { Database, ExternalLink, FileText, RefreshCw, Search, ShieldCheck, Trash2, Upload } from "lucide-react";
import { FormEvent, useMemo, useRef, useState } from "react";
import { Panel } from "../../components/Panel";
import {
  useAssetsQuery,
  useDeleteFinancialKnowledgeMutation,
  useFinancialKnowledgeCoverageQuery,
  useFinancialKnowledgeDocumentsQuery,
  useFinancialKnowledgeSearchQuery,
  useRefreshFinancialKnowledgeMutation,
  useRequestFinancialKnowledgeFullTextMutation,
  useUploadFinancialKnowledgeMutation,
} from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function FinancialKnowledgePanel() {
  const { l } = useI18n();
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const assets = useAssetsQuery();
  const asset = assets.data?.find((item) => item.id === assetId);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [documentType, setDocumentType] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const coverage = useFinancialKnowledgeCoverageQuery(asset?.ticker);
  const search = useFinancialKnowledgeSearchQuery(query, asset?.ticker, documentType || undefined);
  const documents = useFinancialKnowledgeDocumentsQuery(asset?.ticker);
  const upload = useUploadFinancialKnowledgeMutation();
  const remove = useDeleteFinancialKnowledgeMutation();
  const refresh = useRefreshFinancialKnowledgeMutation();
  const requestFullText = useRequestFinancialKnowledgeFullTextMutation();
  const privateDocuments = useMemo(
    () => (documents.data ?? []).filter((item) => item.source_kind === "user_upload"),
    [documents.data],
  );
  const coverageValue = coverage.data?.metadata_coverage_ratio ?? 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.trim().length >= 2) setQuery(draft.trim());
  };

  return (
    <Panel
      eyebrow={l("研究资料", "Research sources")}
      title={l("金融知识库", "Financial knowledge base")}
      actions={<button className="ghost-button" type="button" disabled={refresh.isPending} onClick={() => refresh.mutate("incremental")}>
        <RefreshCw size={14} /> {refresh.isPending ? l("已创建更新任务", "Update queued") : l("更新目录", "Refresh catalog")}
      </button>}
    >
      <div className="knowledge-intro">
        <div><Database size={20} aria-hidden="true" /><p><strong>{l("先检索，再让 AI 解读", "Retrieve first, then ask AI to explain")}</strong>{l("公告、规则、宏观资料和你的私有文档均显示原始来源；没有 API Key 也能搜索。", "Announcements, rules, macro references and private documents retain original sources; search works without an API key.")}</p></div>
        <div className="knowledge-coverage" aria-label={l("知识覆盖", "Knowledge coverage")}>
          <span><strong>{Math.round(coverageValue * 100)}%</strong>{l("元数据覆盖", "metadata")}</span>
          <span><strong>{coverage.data?.full_text_count ?? 0}</strong>{l("正文", "full text")}</span>
          <span><strong>{coverage.data?.semantic_search_available ? l("可用", "Ready") : l("关键词", "Lexical")}</strong>{l("检索模式", "search mode")}</span>
        </div>
      </div>

      <form className="knowledge-search" onSubmit={submit}>
        <div className="knowledge-search__field"><Search size={17} aria-hidden="true" /><input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={asset ? l(`搜索 ${asset.name} 的公告、规则或财务概念`, `Search ${asset.name} disclosures, rules or concepts`) : l("搜索公司、公告、规则或财务概念", "Search companies, disclosures, rules or concepts")} /></div>
        <select value={documentType} onChange={(event) => setDocumentType(event.target.value)} aria-label={l("资料类型", "Document type")}>
          <option value="">{l("全部资料", "All documents")}</option>
          <option value="announcement_metadata">{l("公司公告", "Disclosures")}</option>
          <option value="regulation">{l("监管规则", "Regulations")}</option>
          <option value="market_rule">{l("交易规则", "Market rules")}</option>
          <option value="user_document">{l("我的资料", "My documents")}</option>
        </select>
        <button className="primary-button" type="submit" disabled={draft.trim().length < 2}>{l("搜索资料", "Search")}</button>
      </form>

      {query ? <div className="knowledge-results" aria-live="polite">
        <div className="knowledge-results__header"><strong>{l(`“${query}” 的检索结果`, `Results for “${query}”`)}</strong><span>{search.isFetching ? l("检索中…", "Searching...") : l(`${search.data?.length ?? 0} 条可追溯资料`, `${search.data?.length ?? 0} traceable sources`)}</span></div>
        {search.isError ? <div className="knowledge-empty">{l("当前无法读取知识库，请稍后重试。", "The knowledge base is unavailable. Try again later.")}</div> : null}
        {!search.isFetching && !search.isError && !search.data?.length ? <div className="knowledge-empty">{l("没有找到匹配资料。系统不会把通用说明伪装成公司级证据。", "No matching source was found. Generic guidance is never presented as company evidence.")}</div> : null}
        {search.data?.map((item) => <article className="knowledge-result" key={item.citation_id ?? item.chunk_id ?? item.document.id}>
          <div className="knowledge-result__top"><span className={`knowledge-source-kind knowledge-source-kind--${item.document.source_kind}`}>{item.document.source_kind === "user_upload" ? l("我的资料", "Private") : item.document.source_name}</span><span>{new Date(item.document.published_at).toLocaleDateString()}</span></div>
          <h3>{item.document.title}</h3>
          <p>{item.snippet ?? item.document.content.slice(0, 240)}</p>
          <div className="knowledge-result__meta"><span>{item.page_or_section ?? l("元数据", "metadata")}</span><span>{item.pit_status === "proven" ? l("时间已证明", "PIT proven") : l("历史时间为研究假设", "PIT assumed")}</span><span>{item.coverage_status === "complete" ? l("正文完整", "Full text") : l("覆盖不完整", "Partial")}</span></div>
          <div className="knowledge-result__footer"><code>{item.citation_id}</code><span className="knowledge-result__actions">{item.coverage_status !== "complete" && item.document.source_kind === "official_public" ? <button type="button" disabled={requestFullText.isPending} onClick={() => requestFullText.mutate(item.document.id)}>{l("请求正文", "Fetch full text")}</button> : null}{item.document.source_url ? <a href={item.document.source_url} target="_blank" rel="noreferrer">{l("打开官方原文", "Open original")} <ExternalLink size={13} /></a> : null}</span></div>
        </article>)}
      </div> : <div className="knowledge-empty knowledge-empty--prompt"><ShieldCheck size={18} /><span>{l("搜索结果会显示来源、发布日期、页码或条款、PIT 状态和引用 ID。", "Results show source, date, page or section, PIT status and citation ID.")}</span></div>}

      <details className="knowledge-private">
        <summary>{l(`管理个人资料（${privateDocuments.length}）`, `Manage private documents (${privateDocuments.length})`)}</summary>
        <p>{l("支持 PDF、DOCX、TXT 和 Markdown。资料仅绑定当前账号，删除时会同时移除切片和向量索引。", "Supports PDF, DOCX, TXT and Markdown. Documents are owner-isolated; deleting also removes chunks and vectors.")}</p>
        <input ref={fileInput} hidden type="file" accept=".pdf,.docx,.txt,.md,.markdown" onChange={(event) => { const file = event.target.files?.[0]; if (file) upload.mutate({ file, assetId }); event.currentTarget.value = ""; }} />
        <button className="ghost-button" type="button" disabled={upload.isPending} onClick={() => fileInput.current?.click()}><Upload size={14} /> {upload.isPending ? l("正在解析…", "Parsing...") : l("上传个人资料", "Upload document")}</button>
        {upload.isError ? <p className="knowledge-error">{upload.error.message}</p> : null}
        <div className="knowledge-private__list">{privateDocuments.map((item) => <div key={item.id}><FileText size={15} /><span><strong>{item.title}</strong><small>{new Date(item.available_at).toLocaleDateString()} · {item.content_scope === "full_text" ? l("已索引", "Indexed") : l("仅元数据", "Metadata")}</small></span><button type="button" title={l("删除", "Delete")} onClick={() => remove.mutate(item.id)}><Trash2 size={14} /></button></div>)}</div>
      </details>
      <p className="knowledge-boundary">{l("知识库负责解释事实和规则，不生成方向、收益或回撤概率；数值预测仍来自量化模型。", "The knowledge base explains facts and rules; direction, return and drawdown numbers still come from quantitative models.")}</p>
    </Panel>
  );
}
