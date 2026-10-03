import { sendChat } from "./api.js";
import {
  openDocumentBySourceKey,
  updateChatGroupOptions,
  updateChatScopeSummary,
} from "./documents.js";
import { $, errorMessage, escapeHtml, icon, renderMarkdown } from "./ui.js";


let history = [];
let busy = false;
const now = () =>
  new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
const scrollBottom = () => {
  $("chatBody").scrollTop = $("chatBody").scrollHeight;
};


function addUserMessage(text) {
  const row = document.createElement("div");
  row.className = "message-row user";
  row.innerHTML = `<div class="message-column"><div class="bubble">${escapeHtml(text)}</div><div class="time">${now()}</div></div>`;
  $("messages").append(row);
  scrollBottom();
}


function sourceChips(sources) {
  if (!sources.length) return "";
  return sources
    .map(
      (source) => {
        const location = source.heading || `Đoạn ${Number(source.chunk_index) + 1}`;
        const hasSimilarity = source.similarity !== null && source.similarity !== undefined;
        const similarity = hasSimilarity && Number.isFinite(Number(source.similarity))
          ? ` · Độ tương đồng: ${Number(source.similarity).toFixed(3)}`
          : "";
        return `
          <button class="source-chip" type="button" data-source-key="${escapeHtml(source.source_key)}" title="Mở tài liệu">
            [${escapeHtml(source.citation)}] ${escapeHtml(source.title)} · ${escapeHtml(location)}${similarity}
          </button>`;
      },
    )
    .join("");
}


function citedSources(answer, sources) {
  const citations = new Set(
    [...String(answer).matchAll(/\[S(\d+)\]/g)].map((match) => `S${match[1]}`),
  );
  const selected = citations.size
    ? sources.filter((source) => citations.has(source.citation))
    : sources;
  return selected.slice(0, 5);
}


function sourceAssets(sources) {
  const unique = new Map();
  for (const source of sources) {
    for (const asset of source.assets || []) {
      if (!unique.has(asset.id)) {
        unique.set(asset.id, {
          ...asset,
          citation: source.citation,
          sourceTitle: source.title,
          sectionPath: source.section_path || [],
        });
      }
    }
  }
  return [...unique.values()];
}


function assetGallery(assets) {
  if (!assets.length) return "";
  return `
    <div class="rag-source-images" aria-label="Hình ảnh tài liệu tham khảo">
      ${assets
        .map((asset) => {
          const page = Number(asset.page_number);
          const caption = asset.caption
            || `[${asset.citation}] ${asset.sourceTitle} — Trang ${page}`;
          const alt = `${asset.sourceTitle}, trang ${page}`;
          return `
            <figure class="rag-source-image">
              <a href="${escapeHtml(asset.url)}" target="_blank" rel="noopener noreferrer" title="Mở ảnh kích thước lớn">
                <img src="${escapeHtml(asset.url)}" alt="${escapeHtml(alt)}" loading="lazy" decoding="async">
              </a>
              <figcaption>${escapeHtml(caption)}</figcaption>
            </figure>`;
        })
        .join("")}
    </div>`;
}


function referenceBlock(answer, sources, { query = "", scope = "", content = "" } = {}) {
  if (!sources.length) return "";
  const visibleSources = citedSources(answer, sources);
  const assets = sourceAssets(sources);
  return `
    <section class="chat-references" aria-label="Tài liệu tham khảo">
      <div class="reference-title">
        <strong>Tài liệu tham khảo</strong>
        <span>${visibleSources.length} nguồn</span>
      </div>
      <div class="reference-scope"><strong>Phạm vi:</strong> ${escapeHtml(scope || "Tất cả tài liệu đang sử dụng")}</div>
      <div class="source-chips">${sourceChips(visibleSources)}</div>
      ${assetGallery(assets)}
      ${content ? `
        <details class="retrieval-details">
          <summary>Xem nội dung truy xuất</summary>
          <div class="retrieval-query"><strong>Câu hỏi tìm kiếm:</strong> ${escapeHtml(query)}</div>
          <pre>${escapeHtml(content)}</pre>
        </details>` : ""}
    </section>`;
}


function addBotMessage(text, sources = [], referenceData = {}) {
  const row = document.createElement("div");
  row.className = "message-row bot";
  row.innerHTML = `
    <div class="mini-bot">${icon("bot")}</div>
    <div class="message-column">
      <div class="bubble markdown-body">${renderMarkdown(text)}</div>
      ${referenceBlock(text, sources, referenceData)}
      <div class="time">${now()}</div>
    </div>`;
  $("messages").append(row);
  scrollBottom();
}


function showTyping() {
  const row = document.createElement("div");
  row.className = "message-row bot typing";
  row.innerHTML = `<div class="mini-bot">${icon("bot")}</div><div class="message-column"><div class="bubble"><i></i><i></i><i></i></div></div>`;
  $("messages").append(row);
  scrollBottom();
  return row;
}


function trimHistory() {
  while (
    history.length > 12 ||
    history.reduce((total, message) => total + message.content.length, 0) > 24_000
  ) {
    history.splice(0, 2);
  }
}


async function sendMessage() {
  const input = $("chatInput");
  const query = input.value.trim();
  if (!query || busy) return;
  addUserMessage(query);
  input.value = "";
  busy = true;
  input.disabled = true;
  $("sendBtn").disabled = true;
  const typing = showTyping();
  try {
    const selectedType = Number($("chatDocumentType").value);
    const selectedGroup = Number($("chatDocumentGroup").value);
    const data = await sendChat({
      query,
      history,
      top_k: 5,
      ...(selectedType ? { doc_type_id: selectedType } : {}),
      ...(selectedGroup ? { group_ids: [selectedGroup] } : {}),
    });
    typing.remove();
    addBotMessage(data.answer, data.sources || [], {
      query,
      scope: $("chatScopeSummary").textContent,
      content: data.retrieved_content || "",
    });
    history.push(
      { role: "user", content: query },
      { role: "assistant", content: data.answer },
    );
    trimHistory();
  } catch (error) {
    typing.remove();
    addBotMessage(`Không thể trả lời: ${errorMessage(error)}`);
  } finally {
    busy = false;
    input.disabled = false;
    $("sendBtn").disabled = false;
    input.focus();
  }
}


function setChatOpen(open) {
  $("chatPanel").classList.toggle("hidden", !open);
  $("chatLauncher").classList.toggle("hidden", open);
  $("pageShell").classList.toggle(
    "chat-closed",
    !open || window.matchMedia("(max-width:1180px)").matches,
  );
  if (open) {
    $("chatPanel").classList.remove("minimized");
    scrollBottom();
  }
}


export function initializeChat() {
  addBotMessage(
    "Xin chào! Tôi có thể giúp bạn tìm thông tin trong kho tài liệu. Bạn muốn hỏi điều gì?",
  );
  $("sendBtn").addEventListener("click", sendMessage);
  $("chatInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      sendMessage();
    }
  });
  $("chatDocumentType").addEventListener("change", () => {
    updateChatGroupOptions();
    if (history.length) {
      history = [];
      addBotMessage("Đã xóa lịch sử vì phạm vi tài liệu vừa thay đổi.");
    }
  });
  $("chatDocumentGroup").addEventListener("change", () => {
    updateChatScopeSummary();
    if (history.length) {
      history = [];
      addBotMessage("Đã xóa lịch sử vì phạm vi tài liệu vừa thay đổi.");
    }
  });
  $("messages").addEventListener("click", (event) => {
    const source = event.target.closest("[data-source-key]");
    if (source) openDocumentBySourceKey(source.dataset.sourceKey, source.innerText);
  });
  $("minimizeBtn").addEventListener("click", () =>
    $("chatPanel").classList.toggle("minimized"),
  );
  $("expandBtn").addEventListener("click", () => {
    $("chatPanel").classList.remove("minimized");
    $("chatPanel").classList.toggle("expanded");
  });
  $("closeBtn").addEventListener("click", () => {
    $("chatPanel").classList.remove("expanded");
    setChatOpen(false);
  });
  $("chatLauncher").addEventListener("click", () => setChatOpen(true));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") $("chatPanel").classList.remove("expanded");
  });
  if (window.matchMedia("(max-width:1180px)").matches) setChatOpen(false);
}
