const documents = [
  {
    id: 1,
    title: "Chính sách đổi trả sản phẩm",
    desc: "Quy định về điều kiện, thời gian và quy trình đổi trả sản phẩm tại Đông Hải.",
    date: "2024-09-10",
    category: "Chính sách",
    type: "policy",
    tags: ["Chính sách", "Đổi trả"],
  },
  {
    id: 2,
    title: "Hướng dẫn bảo quản giày da",
    desc: "Các bước vệ sinh và bảo quản giày da đúng cách để tăng tuổi thọ sản phẩm.",
    date: "2024-09-08",
    category: "Hướng dẫn",
    type: "guide",
    tags: ["Hướng dẫn", "Bảo quản"],
  },
  {
    id: 3,
    title: "Thông tin sản phẩm Sandal Nữ S32J3",
    desc: "Mô tả chi tiết, chất liệu, kích thước và màu sắc của sản phẩm Sandal Nữ S32J3.",
    date: "2024-09-05",
    category: "Sản phẩm",
    type: "product",
    tags: ["Sản phẩm", "Sandal"],
  },
  {
    id: 4,
    title: "Câu hỏi thường gặp về đặt hàng",
    desc: "Tổng hợp các câu hỏi thường gặp liên quan đến đặt hàng và thanh toán.",
    date: "2024-09-03",
    category: "FAQ",
    type: "faq",
    tags: ["FAQ", "Đặt hàng"],
  },
  {
    id: 5,
    title: "Chính sách vận chuyển",
    desc: "Thông tin về phí vận chuyển, thời gian giao hàng và các khu vực hỗ trợ.",
    date: "2024-08-28",
    category: "Chính sách",
    type: "policy",
    tags: ["Chính sách", "Vận chuyển"],
  },
  {
    id: 6,
    title: "Hướng dẫn chọn size giày",
    desc: "Bảng size và hướng dẫn cách đo chân để chọn size phù hợp.",
    date: "2024-08-25",
    category: "Hướng dẫn",
    type: "guide",
    tags: ["Hướng dẫn", "Size giày"],
  },
  {
    id: 7,
    title: "Thông tin sản phẩm Giày Tây Nam G01",
    desc: "Mô tả chi tiết về chất liệu, thiết kế và bảo hành của sản phẩm Giày Tây Nam G01.",
    date: "2024-08-20",
    category: "Sản phẩm",
    type: "product",
    tags: ["Sản phẩm", "Giày tây"],
  },
  {
    id: 8,
    title: "Quy trình bảo hành sản phẩm",
    desc: "Các bước và điều kiện bảo hành sản phẩm tại Đông Hải.",
    date: "2024-08-15",
    category: "Chính sách",
    type: "policy",
    tags: ["Chính sách", "Bảo hành"],
  },
];

const categories = [
  "Tất cả",
  "Sản phẩm",
  "Chính sách",
  "Hướng dẫn",
  "FAQ",
  "Khác",
];
const PAGE_SIZE = 6;
let activeCategory = "Tất cả";
let currentPage = 1;

const $ = (id) => document.getElementById(id);
const grid = $("documentGrid"),
  tabs = $("categoryTabs"),
  count = $("documentCount");
const search = $("documentSearch"),
  globalSearch = $("globalSearch"),
  sortSelect = $("sortSelect");
const docTypeSelect = $("chatDocumentType");

const icon = (name, cls = "") =>
  `<svg class="ic ${cls}"><use href="#i-${name}"/></svg>`;
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmtDate = (d) => d.split("-").reverse().join("/");

function renderTabs() {
  tabs.innerHTML = categories
    .map(
      (cat) =>
        `<button class="category-tab ${cat === activeCategory ? "active" : ""}" role="tab" aria-selected="${cat === activeCategory}" data-cat="${cat}">${cat}</button>`,
    )
    .join("");
  tabs.querySelectorAll("button").forEach((btn) =>
    btn.addEventListener("click", () => {
      activeCategory = btn.dataset.cat;
      currentPage = 1;
      renderTabs();
      renderDocuments();
    }),
  );
}

function getFilteredDocuments() {
  const term = (search.value.trim() || globalSearch.value.trim()).toLowerCase();
  let result = documents.filter(
    (doc) => activeCategory === "Tất cả" || doc.category === activeCategory,
  );
  if (term)
    result = result.filter((doc) =>
      `${doc.title} ${doc.desc} ${doc.tags.join(" ")}`
        .toLowerCase()
        .includes(term),
    );
  const sorters = {
    newest: (a, b) => b.date.localeCompare(a.date),
    oldest: (a, b) => a.date.localeCompare(b.date),
    az: (a, b) => a.title.localeCompare(b.title, "vi"),
  };
  return result.sort(sorters[sortSelect.value]);
}

function renderDocuments() {
  const data = getFilteredDocuments();
  const pages = Math.max(1, Math.ceil(data.length / PAGE_SIZE));
  currentPage = Math.min(currentPage, pages);
  count.textContent = data.length;

  const slice = data.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  );
  grid.innerHTML = slice.length
    ? slice
        .map(
          (doc) => `
    <article class="doc-card" data-type="${doc.type}" tabindex="0">
      <div class="doc-icon">${icon("file")}</div>
      <div class="doc-main">
        <div class="doc-top">
          <div class="doc-title">${esc(doc.title)}</div>
          <button class="more-btn" aria-label="Tùy chọn">${icon("more")}</button>
        </div>
        <div class="doc-desc">${esc(doc.desc)}</div>
        <div class="doc-foot">
          <div class="tags">${doc.tags.map((tag, i) => `<span class="tag ${i === 0 ? "primary" : ""}">${esc(tag)}</span>`).join("")}</div>
          <span class="doc-date">${icon("cal")}${fmtDate(doc.date)}</span>
        </div>
      </div>
    </article>`,
        )
        .join("")
    : `<div class="empty"><strong>Không tìm thấy tài liệu</strong>Thử đổi từ khóa hoặc chọn danh mục khác.</div>`;
  renderPagination(pages);
}

function renderPagination(pages) {
  const nav = $("pagination");
  if (pages <= 1) {
    nav.innerHTML = "";
    return;
  }
  let html = `<button class="page-btn" data-page="${currentPage - 1}" aria-label="Trang trước" ${currentPage === 1 ? "disabled" : ""}>${icon("left")}</button>`;
  for (let p = 1; p <= pages; p++)
    html += `<button class="page-btn ${p === currentPage ? "active" : ""}" data-page="${p}" ${p === currentPage ? 'aria-current="page"' : ""}>${p}</button>`;
  html += `<button class="page-btn" data-page="${currentPage + 1}" aria-label="Trang sau" ${currentPage === pages ? "disabled" : ""}>${icon("right")}</button>`;
  nav.innerHTML = html;
  nav.querySelectorAll("button:not(:disabled)").forEach((b) =>
    b.addEventListener("click", () => {
      currentPage = Number(b.dataset.page);
      renderDocuments();
    }),
  );
}

const resetAndRender = () => {
  currentPage = 1;
  renderDocuments();
};
search.addEventListener("input", () => {
  globalSearch.value = search.value;
  resetAndRender();
});
globalSearch.addEventListener("input", () => {
  search.value = globalSearch.value;
  resetAndRender();
});
sortSelect.addEventListener("change", resetAndRender);
renderTabs();
renderDocuments();

/* ---------- Chat ---------- */
const messages = $("messages"),
  chatBody = $("chatBody"),
  chatInput = $("chatInput");
const chatPanel = $("chatPanel"),
  launcher = $("chatLauncher"),
  pageShell = $("pageShell");

const now = () =>
  new Date().toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });
const scrollBottom = () => {
  chatBody.scrollTop = chatBody.scrollHeight;
};

function addBotMessage(text, withSource = false) {
  const row = document.createElement("div");
  row.className = "message-row bot";
  row.innerHTML = `
    <div class="mini-bot">${icon("bot")}</div>
    <div class="message-column">
      <div class="bubble">${esc(text)}</div>
      ${
        withSource
          ? `
        <div class="source-card">
          <div class="source-icon">${icon("file")}</div>
          <div><div class="source-title">Chính sách đổi trả sản phẩm</div><div class="source-meta">1.2 MB · Cập nhật 10/09/2024</div></div>
          ${icon("right")}
        </div>
        <div class="feedback">
          <button aria-label="Hữu ích">${icon("up")}</button>
          <button aria-label="Chưa hữu ích">${icon("down")}</button>
          <button aria-label="Sao chép">${icon("copy")}</button>
        </div>`
          : ""
      }
      <div class="time">${now()}</div>
    </div>`;
  messages.appendChild(row);
  scrollBottom();
  return row;
}

function addUserMessage(text) {
  const row = document.createElement("div");
  row.className = "message-row user";
  row.innerHTML = `<div class="message-column"><div class="bubble">${esc(text)}</div><div class="time">${now()}</div></div>`;
  messages.appendChild(row);
  scrollBottom();
}

function showTyping() {
  const row = document.createElement("div");
  row.className = "message-row bot typing";
  row.innerHTML = `<div class="mini-bot">${icon("bot")}</div><div class="message-column"><div class="bubble"><i></i><i></i><i></i></div></div>`;
  messages.appendChild(row);
  scrollBottom();
  return row;
}

function bootstrapChat() {
  addBotMessage(
    "Xin chào! Tôi có thể giúp bạn tìm kiếm thông tin từ tài liệu của công ty. Bạn có câu hỏi gì không?",
  );
  addUserMessage("Chính sách đổi trả sản phẩm như thế nào?");
  addBotMessage(
    "Theo tài liệu “Chính sách đổi trả sản phẩm”, quy định như sau:\n\n1. Thời gian đổi trả: trong vòng 7 ngày kể từ ngày nhận hàng.\n2. Điều kiện: sản phẩm còn nguyên tem, nhãn, chưa qua sử dụng.\n3. Quy trình: liên hệ bộ phận CSKH hoặc mang trực tiếp đến cửa hàng.\n\nBạn có muốn xem chi tiết tài liệu gốc không?",
    true,
  );
}
bootstrapChat();

function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;
  addUserMessage(text);
  chatInput.value = "";
  const typing = showTyping();
  // TODO: thay bằng lời gọi RAG_SERVICE, gửi kèm docType = docTypeSelect.value
  setTimeout(() => {
    typing.remove();
    addBotMessage(
      "Đây là phản hồi demo từ Bot RAG. Khi tích hợp API, nội dung này sẽ được lấy trực tiếp từ RAG_SERVICE và các tài liệu liên quan.",
    );
  }, 700);
}
$("sendBtn").addEventListener("click", sendMessage);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.isComposing) {
    e.preventDefault();
    sendMessage();
  } // isComposing: không gửi nhầm khi đang gõ tiếng Việt (Telex/VNI)
});

function setChatOpen(open) {
  chatPanel.classList.toggle("hidden", !open);
  launcher.classList.toggle("hidden", open);
  pageShell.classList.toggle(
    "chat-closed",
    !open || window.matchMedia("(max-width:1180px)").matches,
  );
  if (open) {
    chatPanel.classList.remove("minimized");
    scrollBottom();
  }
}
$("minimizeBtn").addEventListener("click", () =>
  chatPanel.classList.toggle("minimized"),
);
$("expandBtn").addEventListener("click", () => {
  chatPanel.classList.remove("minimized");
  chatPanel.classList.toggle("expanded");
});
$("closeBtn").addEventListener("click", () => {
  chatPanel.classList.remove("expanded");
  setChatOpen(false);
});
launcher.addEventListener("click", () => setChatOpen(true));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") chatPanel.classList.remove("expanded");
});

// Màn hình nhỏ: chat là cửa sổ nổi, mặc định thu gọn thành nút mở
if (window.matchMedia("(max-width:1180px)").matches) setChatOpen(false);
