import {
  clearConversations,
  createAdminUser,
  createPermissionGroup,
  deletePermissionGroup,
  deleteConversation,
  getConversation,
  getConversations,
  getDocument,
  getDocumentBySourceKey,
  getDocuments,
  getHealth,
  getAiProviders,
  getAdminUsers,
  getCurrentUser,
  getPermissionGroups,
  getLatestProductDetails,
  login,
  logout,
  resetAdminUserPassword,
  searchProductsByImage,
  saveConversationMessage,
  getTaxonomy,
  sendChat,
  updateAdminUser,
  updatePermissionGroup,
  updatePermissionScopes,
} from "./api.js?v=20261022-chat-history-4";

const STORE_KEY = "rag-client-conversations-v2";
const PREF_KEY = "rag-client-preferences-v2";
const DEBUG_MODE =
  new URLSearchParams(window.location.search).get("debug")?.toLowerCase() ===
  "true";
const defaults = {
  theme: "light",
  accent: "indigo",
  font: "normal",
  aiProvider: "",
  dataSource: "auto",
};
const starterContent = {
  title: "Bạn muốn tìm thông tin gì?",
  detail: "Hỏi về tài liệu, sản phẩm, tồn kho hoặc gửi hình ảnh để nhận diện.",
  cards: [
    {
      title: "Thời gian làm việc",
      description: "Tra cứu quy định trong tài liệu",
      question: "Quy định về thời gian làm việc như thế nào?",
      icon: "#i-type",
    },
    {
      title: "Sản phẩm mới",
      description: "Xem các sản phẩm mới trong tháng",
      question: "Các sản phẩm mới trong tháng này là gì?",
      icon: "#i-spark",
    },
    {
      title: "Sản phẩm còn hàng",
      description: "Kiểm tra catalog và tồn kho",
      question: "Các sản phẩm hiện đang còn hàng là gì?",
      icon: "#i-table",
    },
  ],
};
const $ = (id) => document.getElementById(id);

const app = {
  chats: [],
  currentId: "",
  prefs: { ...defaults },
  busy: false,
  controller: null,
  toastTimer: null,
  drawer: "",
  taxonomy: [],
  documents: [],
  documentsLoaded: false,
  composerResizeObserver: null,
  aiProviders: [],
  defaultAiProvider: "",
  productImageFile: null,
  productImagePreviewUrl: "",
  currentUser: null,
  authBusy: false,
  adminGroups: [],
  adminUsers: [],
  adminEditingGroupId: "",
  adminEditingUserId: "",
  adminLoaded: false,
};

function loadJSON(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function saveJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

function newId() {
  return crypto.randomUUID();
}

function createChat() {
  return {
    id: newId(),
    title: "Cuộc trò chuyện mới",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    messages: [],
    persisted: false,
  };
}

function currentChat() {
  return app.chats.find((chat) => chat.id === app.currentId);
}

function conversationStoreKey() {
  return app.currentUser?.id ? `${STORE_KEY}:${app.currentUser.id}` : "";
}

function hydrateStoredMessage(message) {
  const metadata = message.metadata || {};
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    dataSource: message.data_source || "documents",
    sources: message.sources || [],
    productSources: metadata.product_sources || [],
    productResult: metadata.product_result || null,
    retrievedContent: metadata.retrieved_content || "",
    query: metadata.query || "",
    scope: metadata.scope || "",
    imageSearch: Boolean(metadata.image_search),
    imageSearchLowConfidence: Boolean(metadata.image_search_low_confidence),
    attachmentName: metadata.attachment_name || "",
    attachmentPreview: metadata.attachment_url || "",
    createdAt: message.created_at,
  };
}

async function ensureConversationLoaded(chat) {
  if (!chat?.persisted || Array.isArray(chat.messages)) return;
  const detail = await getConversation(chat.id);
  chat.title = detail.title;
  chat.createdAt = detail.created_at;
  chat.updatedAt = detail.updated_at;
  chat.messages = (detail.messages || []).map(hydrateStoredMessage);
}

async function persistClientMessage(chat, message) {
  if (!chat || !message) return null;
  message.id ||= newId();
  const stored = await saveConversationMessage(chat.id, {
    id: message.id,
    conversation_title: chat.title,
    role: message.role,
    content: message.content,
    data_source: message.dataSource || null,
    ai_provider: message.aiProvider || null,
    sources: message.sources || [],
    metadata: {
      product_sources: message.productSources || [],
      product_result: message.productResult || null,
      retrieved_content: message.retrievedContent || "",
      query: message.query || "",
      scope: message.scope || "",
      image_search: Boolean(message.imageSearch),
      image_search_low_confidence: Boolean(message.imageSearchLowConfidence),
      attachment_name: message.attachmentName || "",
    },
  });
  message.id = stored.id;
  message.createdAt = stored.created_at;
  chat.persisted = true;
  return stored;
}

async function loadUserChats() {
  const key = conversationStoreKey();
  const saved = key ? loadJSON(key, {}) : {};
  const cachedChats = (Array.isArray(saved.chats) ? saved.chats : []).map(
    (chat) => ({
      ...chat,
      id: /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
        chat.id || "",
      )
        ? chat.id
        : newId(),
    }),
  );
  try {
    const result = await getConversations(20);
    const remoteIds = new Set();
    app.chats = (result.conversations || []).map((conversation) => {
      remoteIds.add(conversation.id);
      return {
        id: conversation.id,
        title: conversation.title,
        createdAt: conversation.created_at,
        updatedAt: conversation.updated_at,
        messages: null,
        persisted: true,
      };
    });
    for (const cached of cachedChats) {
      if (!remoteIds.has(cached.id)) {
        app.chats.push({ ...cached, persisted: false });
      }
    }
  } catch (error) {
    app.chats = cachedChats;
    toast(`Không tải được lịch sử từ máy chủ: ${error.message}`);
  }
  if (!app.chats.length) app.chats.push(createChat());
  app.currentId = app.chats.some((chat) => chat.id === saved.currentId)
    ? saved.currentId
    : app.chats[0].id;
  try {
    await ensureConversationLoaded(currentChat());
  } catch (error) {
    toast(`Không tải được cuộc trò chuyện: ${error.message}`);
  }
  renderHistory();
  renderMessages();
}

function storeChats() {
  const key = conversationStoreKey();
  if (!key) return;
  const chats = app.chats.slice(0, 20).map((chat) => ({
    ...chat,
    messages: Array.isArray(chat.messages) ? chat.messages.slice(-70) : [],
  }));
  saveJSON(key, { chats, currentId: app.currentId });
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.setAttribute("aria-hidden", "true");
  svg.appendChild(use);
  return svg;
}

function toast(message) {
  clearTimeout(app.toastTimer);
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  app.toastTimer = setTimeout(() => $("toast").classList.add("hidden"), 2600);
}

async function copyText(value) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
    } else {
      const input = document.createElement("textarea");
      input.value = value;
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.append(input);
      input.select();
      const copied = document.execCommand("copy");
      input.remove();
      if (!copied) throw new Error("Clipboard is unavailable");
    }
    toast("Đã sao chép nội dung");
  } catch {
    toast("Không thể sao chép. Hãy thử sao chép thủ công.");
  }
}

function updateResolvedTheme() {
  const wantsDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme =
    app.prefs.theme === "system"
      ? wantsDark
        ? "dark"
        : "light"
      : app.prefs.theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.content =
      document.documentElement.dataset.theme === "dark" ? "#14161c" : "#ffffff";
  }
}

function applyPrefs() {
  document.documentElement.dataset.accent = app.prefs.accent;
  document.documentElement.dataset.font = app.prefs.font;
  updateResolvedTheme();

  document.querySelectorAll(".theme-choice").forEach((element) => {
    const active = element.dataset.theme === app.prefs.theme;
    element.classList.toggle("active", active);
    element.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll(".accent-choice").forEach((element) => {
    const active = element.dataset.accent === app.prefs.accent;
    element.classList.toggle("active", active);
    element.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll(".font-choice").forEach((element) => {
    const active = element.dataset.font === app.prefs.font;
    element.classList.toggle("active", active);
    element.setAttribute("aria-pressed", String(active));
  });
}

function syncAiProviderSelect() {
  const select = $("aiProviderSelect");
  const available = app.aiProviders.filter((item) => item.available);
  const availableIds = available.map((item) => item.id);
  const selected = availableIds.includes(app.prefs.aiProvider)
    ? app.prefs.aiProvider
    : availableIds.includes(app.defaultAiProvider)
      ? app.defaultAiProvider
      : availableIds[0] || "";
  app.prefs.aiProvider = selected;
  select.value = selected;
  select.disabled = app.busy || available.length === 0;
  const provider = app.aiProviders.find((item) => item.id === selected);
  select.title = provider
    ? `${provider.label} — ${provider.model}`
    : "Chưa có provider AI được cấu hình API key";
}

function syncStarterContent() {
  const content = starterContent;
  const emptyState = $("emptyState");
  emptyState.querySelector("h1").textContent = content.title;
  emptyState.querySelector(".welcome-detail").textContent = content.detail;
  const cards = [...emptyState.querySelectorAll("[data-suggestion]")];
  cards.forEach((card, index) => {
    const item = content.cards[index];
    if (!item) return;
    card.dataset.suggestion = item.question;
    card.querySelector("strong").textContent = item.title;
    card.querySelector("small").textContent = item.description;
    card.querySelector(".starter-icon use").setAttribute("href", item.icon);
  });
}

function syncDataSource() {
  app.prefs.dataSource = "auto";
  $("documentsButton").classList.toggle("hidden", !DEBUG_MODE);
  $("scopePanel").classList.remove("hidden");
  $("productImageButton").classList.remove("hidden");
  $("aiProviderControl").classList.toggle("hidden", !DEBUG_MODE);
  if (!app.productImageFile) {
    $("messageInput").placeholder =
      "Hỏi về tài liệu, sản phẩm, tồn kho hoặc gửi hình ảnh...";
  }
  $("composerHint").textContent =
    "Trợ lý tự động chọn tài liệu hoặc kho sản phẩm";
  syncStarterContent();
  requestAnimationFrame(updateComposerDockHeight);
}

async function loadAiProviders() {
  const select = $("aiProviderSelect");
  try {
    const result = await getAiProviders();
    app.aiProviders = Array.isArray(result.providers) ? result.providers : [];
    app.defaultAiProvider = result.default || "";
    select.replaceChildren();
    for (const provider of app.aiProviders) {
      const option = document.createElement("option");
      option.value = provider.id;
      option.disabled = !provider.available;
      option.textContent = provider.available
        ? provider.label
        : `${provider.label} (chưa cấu hình)`;
      option.title = provider.model;
      select.append(option);
    }
    syncAiProviderSelect();
    saveJSON(PREF_KEY, app.prefs);
  } catch (error) {
    select.replaceChildren();
    const option = document.createElement("option");
    option.textContent = "Không tải được AI";
    select.append(option);
    select.disabled = true;
    select.title = error.message;
  }
}

function sanitizeHTML(html) {
  const documentNode = new DOMParser().parseFromString(html, "text/html");
  documentNode
    .querySelectorAll(
      "script, style, iframe, object, embed, form, input, button",
    )
    .forEach((node) => node.remove());

  documentNode.body.querySelectorAll("*").forEach((element) => {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim().toLowerCase();
      if (name.startsWith("on") || name === "style")
        element.removeAttribute(attribute.name);
      if (
        (name === "href" || name === "src") &&
        /^(javascript|data:text\/html):/.test(value)
      ) {
        element.removeAttribute(attribute.name);
      }
    }
    if (element.tagName === "A") {
      element.setAttribute("target", "_blank");
      element.setAttribute("rel", "noopener noreferrer");
    }
  });
  return documentNode.body.innerHTML;
}

function markdownFragment(markdown) {
  const template = document.createElement("template");
  const raw = window.marked?.parse
    ? window.marked.parse(markdown || "", { gfm: true, breaks: true })
    : `<p>${String(markdown || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll("\n", "<br>")}</p>`;
  template.innerHTML = sanitizeHTML(raw);

  template.content.querySelectorAll("table").forEach((table) => {
    if (table.parentElement?.classList.contains("table-wrap")) return;
    const wrapper = document.createElement("div");
    wrapper.className = "table-wrap";
    wrapper.tabIndex = 0;
    wrapper.setAttribute("role", "region");
    wrapper.setAttribute("aria-label", "Bảng dữ liệu, có thể cuộn ngang");
    const columnCount = Math.max(
      1,
      ...[...table.rows].map((row) => row.cells.length),
    );
    table.style.setProperty("--table-columns", String(columnCount));
    wrapper.classList.toggle("table-wrap-wide", columnCount >= 6);
    table.replaceWith(wrapper);
    wrapper.append(table);
  });

  template.content.querySelectorAll("pre").forEach((pre) => {
    if (pre.parentElement?.classList.contains("code-wrap")) return;
    const wrapper = document.createElement("div");
    wrapper.className = "code-wrap";
    const bar = document.createElement("div");
    bar.className = "code-topbar";
    const code = pre.querySelector("code");
    const languageClass = [...(code?.classList || [])].find((item) =>
      item.startsWith("language-"),
    );
    const label = document.createElement("span");
    label.textContent = languageClass?.replace("language-", "") || "Mã";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "code-copy";
    button.append(icon("copy"), document.createTextNode("Sao chép"));
    button.addEventListener("click", () =>
      copyText(code?.textContent || pre.textContent || ""),
    );
    bar.append(label, button);
    pre.replaceWith(wrapper);
    wrapper.append(bar, pre);
  });
  return template.content;
}

function visibleMessageContent(message) {
  const content = String(message.content || "");
  if (DEBUG_MODE || message.dataSource === "products") return content;

  return content
    .replace(/\s*\[(?:S\d+(?:\s*(?:[,;/-]|\s)\s*S\d+)*)\]/gi, "")
    .replace(/[ \t]+([,.;:!?])/g, "$1");
}

function formatTime(value) {
  const date = new Date(value || Date.now());
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatAdminDateTime(value) {
  if (!value) return "Chưa đăng nhập";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Không xác định";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function sourceLabel(source) {
  const parts = [source.title];
  const heading = source.heading || source.section_path?.at?.(-1);
  if (heading && heading !== source.title) parts.push(heading);
  if (Number.isFinite(source.similarity) && source.similarity > 0) {
    parts.push(`Độ tương đồng: ${source.similarity.toFixed(3)}`);
  }
  return parts.filter(Boolean).join(" · ");
}

function citedSources(answer, sources) {
  const citations = new Set();
  for (const match of String(answer || "").matchAll(
    /\[([^\]]*S\d+[^\]]*)\]/gi,
  )) {
    for (const citation of match[1].match(/S\d+/gi) || [])
      citations.add(citation.toUpperCase());
  }
  if (!citations.size) return sources;
  const selected = sources.filter((source) =>
    citations.has(String(source.citation).toUpperCase()),
  );
  return selected.length ? selected : sources;
}

function uniqueAssets(sources) {
  const assets = new Map();
  for (const source of sources) {
    for (const asset of source.assets || []) {
      if (!assets.has(asset.id)) assets.set(asset.id, { ...asset, source });
    }
  }
  return [...assets.values()];
}

function buildAssetGallery(sources, { showDebugMetadata = false } = {}) {
  const assets = uniqueAssets(sources);
  if (!assets.length) return null;

  const gallery = document.createElement("div");
  gallery.className = "rag-asset-gallery";
  for (const asset of assets) {
    const figure = document.createElement("figure");
    const image = document.createElement("img");
    image.src = asset.url;
    image.alt =
      asset.caption || `${asset.source.title}, trang ${asset.page_number}`;
    image.loading = "lazy";
    image.addEventListener("click", () =>
      window.open(asset.url, "_blank", "noopener"),
    );

    const caption = document.createElement("figcaption");
    const captionText =
      asset.caption || asset.source.title || "Hình ảnh tài liệu";
    caption.textContent = showDebugMetadata
      ? `[${asset.source.citation}] ${captionText} — Trang ${asset.page_number}`
      : captionText;
    figure.append(image, caption);
    gallery.append(figure);
  }
  return gallery;
}

function buildPublicDocumentImages(message) {
  const sources = Array.isArray(message.sources) ? message.sources : [];
  const gallery = buildAssetGallery(sources);
  if (!gallery) return null;

  const section = document.createElement("section");
  section.className = "rag-references rag-public-images";
  const heading = document.createElement("div");
  heading.className = "rag-reference-heading";
  heading.textContent = "Hình ảnh liên quan";
  section.append(heading, gallery);
  return section;
}

function buildReferences(message) {
  const allSources = Array.isArray(message.sources) ? message.sources : [];
  const sources = citedSources(message.content, allSources);
  if (!sources.length && !message.retrievedContent) return null;

  const section = document.createElement("section");
  section.className = "rag-references";
  const heading = document.createElement("div");
  heading.className = "rag-reference-heading";
  heading.textContent = "Tài liệu tham khảo";
  section.append(heading);

  if (message.scope) {
    const scope = document.createElement("p");
    scope.className = "rag-reference-scope";
    scope.textContent = `Phạm vi: ${message.scope}`;
    section.append(scope);
  }

  if (sources.length) {
    const chips = document.createElement("div");
    chips.className = "rag-source-chips";
    for (const source of sources) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "rag-source-chip";
      chip.textContent = `[${source.citation}] ${sourceLabel(source)}`;
      chip.title = "Mở tài liệu nguồn";
      chip.addEventListener("click", () => openSourceDocument(source));
      chips.append(chip);
    }
    section.append(chips);
  }

  // Ảnh có thể nằm ở một chunk nguồn không được LLM trích dẫn trực tiếp.
  // Vì vậy luôn gom assets từ toàn bộ sources mà RAG trả về.
  const gallery = buildAssetGallery(allSources, { showDebugMetadata: true });
  if (gallery) section.append(gallery);

  if (message.retrievedContent) {
    const details = document.createElement("details");
    details.className = "rag-retrieval";
    const summary = document.createElement("summary");
    summary.textContent = "Xem nội dung truy xuất";
    const query = document.createElement("p");
    query.className = "rag-retrieval-query";
    query.textContent = `Câu hỏi tìm kiếm: ${message.query || ""}`;
    const content = document.createElement("pre");
    content.textContent = message.retrievedContent;
    details.append(summary, query, content);
    section.append(details);
  }
  return section;
}

function formatPrice(value) {
  if (value === null || value === undefined || value === "") return "";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "";
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatProductDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN").format(date);
}

function formatProductDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function markdownValue(value) {
  return String(value ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("|", "\\|")
    .replaceAll("\r", " ")
    .replaceAll("\n", " ")
    .trim();
}

function variantIsAvailable(variant) {
  return variant?.available === true || Number(variant?.inventory_quantity) > 0;
}

function optionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function buildImageSearchAnswer(result, products) {
  if (!products.length) {
    return "Chưa nhận diện được sản phẩm trong kho hiện tại.";
  }

  const product = products[0];
  const variants = Array.isArray(product.variants) ? product.variants : [];
  const availableVariants = variants.filter(variantIsAvailable);
  const totalInventory = optionalNumber(product.total_inventory);
  const minimumPrice = optionalNumber(product.minimum_price);
  const maximumPrice = optionalNumber(product.maximum_price);
  const inventorySyncedAt = formatProductDateTime(product.inventory_synced_at);
  const title = markdownValue(
    product.title || product.product_code || "Sản phẩm",
  );
  const code = markdownValue(product.product_code);
  const lines = [];

  if (result.low_confidence) {
    lines.push(
      `Sản phẩm được nhận diện gần nhất là **${title}**${code ? ` (mã **${code}**)` : ""}.`,
    );
  } else {
    lines.push(
      `Sản phẩm được nhận diện từ hình ảnh là **${title}**${code ? ` (mã **${code}**)` : ""}.`,
    );
  }

  lines.push("", "### Thông tin sản phẩm");
  const productDetails = [
    ["Mã sản phẩm", product.product_code],
    ["Tên sản phẩm", product.title],
    ["Loại", product.product_type],
    ["Thương hiệu", product.vendor],
    ["Chất liệu", product.material],
    ["Đế", product.sole],
    ["Chiều cao", product.height],
    ["Màu ảnh khớp", product.matched_color],
  ];
  for (const [label, value] of productDetails) {
    if (value !== null && value !== undefined && String(value).trim()) {
      lines.push(`- **${label}:** ${markdownValue(value)}`);
    }
  }

  if (minimumPrice !== null) {
    const price =
      maximumPrice !== null && maximumPrice !== minimumPrice
        ? `${formatPrice(minimumPrice)} – ${formatPrice(maximumPrice)}`
        : formatPrice(minimumPrice);
    lines.push(`- **Giá:** ${price}`);
  }
  if (product.online_store_url) {
    lines.push(`- [Xem sản phẩm](${product.online_store_url})`);
  }

  lines.push("", "### Tình trạng tồn kho");
  const inventoryLabel =
    product.inventory_status === "in_stock"
      ? "Còn hàng"
      : product.inventory_status === "out_of_stock"
        ? "Hết hàng"
        : "Chưa xác định";
  lines.push(`- **Trạng thái:** ${inventoryLabel}`);
  if (totalInventory !== null) {
    lines.push(`- **Tổng tồn:** ${totalInventory}`);
  }
  if (variants.length) {
    lines.push(
      `- **Biến thể còn hàng:** ${availableVariants.length}/${variants.length}`,
    );
  }
  if (inventorySyncedAt) {
    lines.push(`- **Cập nhật tồn kho:** ${inventorySyncedAt}`);
  }

  if (variants.length) {
    lines.push(
      "",
      "| SKU | Màu | Size | Giá | Tồn kho | Trạng thái |",
      "| --- | --- | --- | ---: | ---: | --- |",
    );
    for (const variant of variants) {
      const quantity = optionalNumber(variant.inventory_quantity);
      const inventoryStatus = variantIsAvailable(variant)
        ? "Còn hàng"
        : variant.available === false || quantity !== null
          ? "Hết hàng"
          : "";
      lines.push(
        `| ${markdownValue(variant.sku)} | ${markdownValue(variant.color)} | ${markdownValue(variant.size)} | ${formatPrice(variant.price)} | ${quantity ?? ""} | ${inventoryStatus} |`,
      );
    }
  }

  return lines.join("\n");
}

function buildProductReferences(message) {
  const products = Array.isArray(message.productSources)
    ? message.productSources
    : [];
  if (!products.length) return null;

  const section = document.createElement("section");
  section.className = "product-references";
  const heading = document.createElement("div");
  heading.className = "rag-reference-heading";
  const resultMeta = message.productResult || null;
  heading.textContent =
    resultMeta?.total != null
      ? `Thông tin và hình ảnh sản phẩm · Hiển thị ${products.length}/${resultMeta.total}`
      : `Thông tin và hình ảnh sản phẩm · ${products.length} kết quả`;
  const grid = document.createElement("div");
  grid.className = "product-source-grid";

  for (const product of products) {
    const card = document.createElement("article");
    card.className = "product-source-card";
    const imageUrls = [
      ...new Set(
        [
          ...(Array.isArray(product.image_urls) ? product.image_urls : []),
          product.image_url,
        ].filter(Boolean),
      ),
    ];
    if (imageUrls.length) {
      card.classList.add("has-gallery");
      const galleryTrigger = document.createElement("button");
      galleryTrigger.type = "button";
      galleryTrigger.className = "product-gallery-trigger";
      galleryTrigger.setAttribute(
        "aria-label",
        imageUrls.length > 1
          ? `Xem album ${imageUrls.length} ảnh của ${product.title || product.product_code}`
          : `Xem ảnh của ${product.title || product.product_code}`,
      );

      const coverImage = document.createElement("img");
      coverImage.src = imageUrls[0];
      coverImage.alt = product.title || product.product_code || "Ảnh sản phẩm";
      coverImage.loading = "lazy";
      coverImage.referrerPolicy = "no-referrer";

      const galleryLabel = document.createElement("span");
      galleryLabel.className = "product-gallery-label";
      galleryLabel.append(icon("image"));
      galleryLabel.append(
        document.createTextNode(
          imageUrls.length > 1 ? `Album · ${imageUrls.length} ảnh` : "Xem ảnh",
        ),
      );

      galleryTrigger.append(coverImage, galleryLabel);
      galleryTrigger.addEventListener("click", () =>
        openProductGallery(product, imageUrls),
      );
      card.append(galleryTrigger);
    }

    const body = document.createElement("div");
    body.className = "product-source-body";
    if (product.matched_color) {
      const match = document.createElement("span");
      match.className = "product-image-match";
      match.textContent = `Màu ${product.matched_color}`;
      body.append(match);
    }
    const title = document.createElement("strong");
    title.textContent = product.title;
    const code = document.createElement("span");
    code.className = "product-source-code";
    code.textContent = product.product_code;

    const variants = Array.isArray(product.variants) ? product.variants : [];
    const available = variants.filter(variantIsAvailable);
    const prices = variants
      .map((item) => Number(item.price))
      .filter(Number.isFinite);
    const minimumPrice = prices.length ? Math.min(...prices) : null;
    const stock = available.reduce(
      (total, item) =>
        total +
        (Number.isFinite(Number(item.inventory_quantity))
          ? Number(item.inventory_quantity)
          : 0),
      0,
    );
    const inventoryLabel =
      product.inventory_status === "in_stock"
        ? "Còn hàng"
        : product.inventory_status === "out_of_stock"
          ? "Hết hàng"
          : "";
    const newestDate = formatProductDate(product.new_at);
    const meta = document.createElement("small");
    meta.textContent = [
      product.product_type,
      formatPrice(minimumPrice),
      inventoryLabel,
      variants.length
        ? `${available.length}/${variants.length} biến thể còn hàng`
        : "",
      stock > 0 ? `Tổng tồn ${stock}` : "",
      newestDate ? `Ngày mới ${newestDate}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    body.append(title, code, meta);
    if (product.online_store_url) {
      const productLink = document.createElement("a");
      productLink.className = "product-page-link";
      productLink.href = product.online_store_url;
      productLink.target = "_blank";
      productLink.rel = "noopener noreferrer";
      productLink.textContent = "Xem sản phẩm";
      body.append(productLink);
    }
    card.append(body);
    grid.append(card);
  }
  section.append(heading, grid);

  if (resultMeta?.has_more) {
    const moreButton = document.createElement("button");
    moreButton.type = "button";
    moreButton.className = "product-load-more";
    moreButton.textContent = "Xem thêm sản phẩm";
    moreButton.addEventListener("click", async () => {
      moreButton.disabled = true;
      moreButton.textContent = "Đang tải…";
      try {
        const response = await getLatestProductDetails({
          page: Number(resultMeta.page || 1) + 1,
          limit: resultMeta.page_size,
          dateFrom: resultMeta.date_from,
          dateTo: resultMeta.date_to,
        });
        const existingCodes = new Set(
          message.productSources.map((item) => item.product_code),
        );
        for (const product of response.products || []) {
          if (!existingCodes.has(product.product_code)) {
            message.productSources.push(product);
            existingCodes.add(product.product_code);
          }
        }
        message.productResult = {
          ...(response.result || resultMeta),
          shown: message.productSources.length,
        };
        try {
          const ownerChat = app.chats.find(
            (chat) =>
              Array.isArray(chat.messages) && chat.messages.includes(message),
          );
          await persistClientMessage(ownerChat, message);
        } catch (error) {
          toast(`Chưa lưu được danh sách mới: ${error.message}`);
        }
        storeChats();
        renderMessages();
      } catch (error) {
        moreButton.disabled = false;
        moreButton.textContent = "Xem thêm sản phẩm";
        toast(error?.message || "Không thể tải thêm sản phẩm.");
      }
    });
    section.append(moreButton);
  }
  return section;
}

function openProductGallery(product, imageUrls) {
  const dialog = $("productGalleryDialog");
  const title = product.title || product.product_code || "Ảnh sản phẩm";
  $("productGalleryTitle").textContent = title;
  $("productGalleryMeta").textContent = [
    product.product_code,
    `${imageUrls.length} ảnh`,
  ]
    .filter(Boolean)
    .join(" · ");

  const gallery = $("productGalleryGrid");
  gallery.replaceChildren();
  imageUrls.forEach((url, imageIndex) => {
    const figure = document.createElement("figure");
    const image = document.createElement("img");
    image.src = url;
    image.alt = `${title} - hình ${imageIndex + 1}`;
    image.loading = imageIndex === 0 ? "eager" : "lazy";
    image.referrerPolicy = "no-referrer";
    const caption = document.createElement("figcaption");
    caption.textContent = `Ảnh ${imageIndex + 1}/${imageUrls.length}`;
    figure.append(image, caption);
    gallery.append(figure);
  });

  dialog.showModal();
}

function buildMessage(message, index) {
  const article = document.createElement("article");
  article.className = `message ${message.role}`;

  if (message.role === "user") {
    const bubble = document.createElement("div");
    bubble.className = "user-message-content";
    const text = document.createElement("span");
    text.textContent = message.content;
    bubble.append(text);
    if (message.attachmentName) {
      const attachment = document.createElement("figure");
      attachment.className = "user-image-attachment";
      if (message.attachmentPreview) {
        const previewButton = document.createElement("button");
        previewButton.type = "button";
        previewButton.className = "user-image-preview";
        previewButton.setAttribute(
          "aria-label",
          `Xem ảnh đã gửi: ${message.attachmentName}`,
        );
        const previewImage = document.createElement("img");
        previewImage.src = message.attachmentPreview;
        previewImage.alt = message.attachmentName;
        previewImage.loading = "lazy";
        previewButton.append(previewImage);
        previewButton.addEventListener("click", () =>
          openProductGallery({ title: message.attachmentName }, [
            message.attachmentPreview,
          ]),
        );
        attachment.append(previewButton);
      }
      const caption = document.createElement("figcaption");
      caption.append(
        icon("image"),
        document.createTextNode(message.attachmentName),
      );
      attachment.append(caption);
      bubble.append(attachment);
    }
    article.append(bubble);
    return article;
  }

  const avatar = document.createElement("div");
  avatar.className = "assistant-avatar";
  avatar.append(icon("spark"));
  const body = document.createElement("div");
  body.className = "assistant-content";
  const name = document.createElement("p");
  name.className = "assistant-name";
  name.textContent = "Ms.Hài (Trợ lý AI nội bộ)";
  const markdown = document.createElement("div");
  markdown.className = "markdown";
  const visibleContent = visibleMessageContent(message);
  markdown.append(markdownFragment(visibleContent));
  body.append(name, markdown);

  const references =
    message.dataSource === "products"
      ? buildProductReferences(message)
      : DEBUG_MODE
        ? buildReferences(message)
        : buildPublicDocumentImages(message);
  if (references) body.append(references);

  const tools = document.createElement("div");
  tools.className = "message-tools";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "tool-button";
  copy.append(icon("copy"), document.createTextNode("Sao chép"));
  copy.addEventListener("click", () => copyText(visibleContent));
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "tool-button";
  retry.disabled = app.busy;
  retry.append(icon("rotate"), document.createTextNode("Trả lời lại"));
  retry.addEventListener("click", () => retryMessage(index));
  const time = document.createElement("span");
  time.className = "message-time";
  time.textContent = formatTime(message.createdAt);
  tools.append(copy);
  if (!message.imageSearch) tools.append(retry);
  tools.append(time);
  body.append(tools);
  article.append(avatar, body);
  return article;
}

function buildThinking() {
  const article = document.createElement("article");
  article.className = "message assistant thinking-message";
  const avatar = document.createElement("div");
  avatar.className = "assistant-avatar";
  avatar.append(icon("spark"));
  const body = document.createElement("div");
  body.className = "assistant-content";
  const name = document.createElement("p");
  name.className = "assistant-name";
  name.textContent = "Đang tìm nguồn thông tin phù hợp…";
  const dots = document.createElement("div");
  dots.className = "typing-dots";
  dots.append(
    document.createElement("span"),
    document.createElement("span"),
    document.createElement("span"),
  );
  body.append(name, dots);
  article.append(avatar, body);
  return article;
}

function renderMessages({ scroll = false } = {}) {
  const chat = currentChat();
  const messages = chat?.messages || [];
  $("emptyState").classList.toggle("hidden", messages.length > 0);
  $("messageList").classList.toggle("hidden", messages.length === 0);
  $("messageList").replaceChildren(...messages.map(buildMessage));
  if (app.busy) $("messageList").append(buildThinking());
  if (scroll)
    requestAnimationFrame(() =>
      $("bottomAnchor").scrollIntoView({ behavior: "smooth" }),
    );
  requestAnimationFrame(updateScrollDownButton);
}

function updateScrollDownButton() {
  const scroller = $("conversationScroll");
  const distanceFromBottom =
    scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  const hasMessages = !$("messageList").classList.contains("hidden");
  $("scrollDownButton").classList.toggle(
    "hidden",
    !hasMessages || distanceFromBottom <= 120,
  );
}

function scrollConversationToBottom() {
  $("conversationScroll").scrollTo({
    top: $("conversationScroll").scrollHeight,
    behavior: "smooth",
  });
}

function updateComposerDockHeight() {
  const height = $("composerForm").closest(".composer-dock")?.offsetHeight;
  if (height)
    $("conversationScroll").parentElement.style.setProperty(
      "--composer-dock-height",
      `${height}px`,
    );
}

function renderHistory() {
  const container = $("conversationHistory");
  container.replaceChildren();
  if (!app.chats.length) {
    const empty = document.createElement("p");
    empty.className = "empty-history";
    empty.textContent = "Chưa có cuộc trò chuyện nào.";
    container.append(empty);
    return;
  }
  for (const chat of app.chats) {
    const row = document.createElement("div");
    row.className = "history-item";
    row.classList.toggle("current", chat.id === app.currentId);
    const select = document.createElement("button");
    select.type = "button";
    select.className = "history-select";
    select.textContent = chat.title;
    select.title = chat.title;
    select.addEventListener("click", async () => {
      app.currentId = chat.id;
      storeChats();
      try {
        await ensureConversationLoaded(chat);
      } catch (error) {
        toast(`Không tải được cuộc trò chuyện: ${error.message}`);
        return;
      }
      renderMessages({ scroll: true });
      closeDrawer();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "history-delete";
    remove.setAttribute("aria-label", `Xóa ${chat.title}`);
    remove.append(icon("trash"));
    remove.addEventListener("click", () => deleteChat(chat.id));
    row.append(select, remove);
    container.append(row);
  }
}

function startNewChat() {
  if (app.busy) stopGeneration();
  const chat = createChat();
  app.chats.unshift(chat);
  app.currentId = chat.id;
  storeChats();
  renderHistory();
  renderMessages();
  closeDrawer();
  $("messageInput").focus();
}

async function deleteChat(id) {
  const chat = app.chats.find((item) => item.id === id);
  if (!chat) return;
  if (chat.persisted) {
    try {
      await deleteConversation(id);
    } catch (error) {
      toast(error.message || "Không thể xóa cuộc trò chuyện.");
      return;
    }
  }
  app.chats = app.chats.filter((chat) => chat.id !== id);
  if (!app.chats.length) app.chats.push(createChat());
  if (app.currentId === id) app.currentId = app.chats[0].id;
  try {
    await ensureConversationLoaded(currentChat());
  } catch (error) {
    toast(`Không tải được cuộc trò chuyện: ${error.message}`);
  }
  storeChats();
  renderHistory();
  renderMessages();
}

function setAdminPanel(name) {
  const target = name === "users" ? "users" : "groups";
  document.querySelectorAll("[data-admin-panel]").forEach((button) => {
    const active = button.dataset.adminPanel === target;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  $("adminGroupsOverview").classList.toggle("hidden", target !== "groups");
  $("adminUsersOverview").classList.toggle("hidden", target !== "users");
  $("adminDrawer").scrollTop = 0;
}

function openDrawer(name) {
  if (name === "documents" && !DEBUG_MODE) return;
  if (name === "admin" && app.currentUser?.role !== "admin") return;
  closeDrawer();
  app.drawer = name;
  if (name === "admin") {
    const adminPage = $("adminDrawer");
    adminPage.classList.remove("hidden");
    document.querySelector(".app-shell").inert = true;
    document.body.classList.add("admin-page-open");
    setAdminPanel("groups");
    ensureAdminData();
    adminPage.querySelector(".admin-back-button")?.focus();
    return;
  }
  const drawer =
    name === "history"
      ? $("historyDrawer")
      : name === "documents"
        ? $("documentsDrawer")
        : $("settingsDrawer");
  drawer.classList.remove("hidden");
  $("overlay").classList.remove("hidden");
  $("overlay").setAttribute("aria-hidden", "false");
  if (name === "history") renderHistory();
  if (name === "documents") ensureDocuments();
  drawer.querySelector("button, input")?.focus();
}

function closeDrawer() {
  const permissionDialog = $("permissionGroupDialog");
  if (permissionDialog?.open) permissionDialog.close();
  const permissionUserDialog = $("permissionUserDialog");
  if (permissionUserDialog?.open) permissionUserDialog.close();
  const createPermissionUserDialog = $("createPermissionUserDialog");
  if (createPermissionUserDialog?.open) createPermissionUserDialog.close();
  app.adminEditingGroupId = "";
  app.adminEditingUserId = "";
  app.drawer = "";
  document
    .querySelectorAll(".side-drawer")
    .forEach((drawer) => drawer.classList.add("hidden"));
  $("adminDrawer").classList.add("hidden");
  document.querySelector(".app-shell").inert = !app.currentUser;
  document.body.classList.remove("admin-page-open");
  $("overlay").classList.add("hidden");
  $("overlay").setAttribute("aria-hidden", "true");
}

function setBusy(value) {
  app.busy = value;
  $("sendButton").classList.toggle("hidden", value);
  $("stopButton").classList.toggle("hidden", !value);
  $("messageInput").disabled = value;
  $("productImageButton").disabled = value;
  $("removeProductImageButton").disabled = value;
  syncAiProviderSelect();
  renderMessages({ scroll: true });
}

function selectedScope() {
  const typeId = $("chatDocumentType").value;
  const groupId = $("chatDocumentGroup").value;
  const type = app.taxonomy.find((item) => String(item.id) === typeId);
  const group = app.taxonomy
    .flatMap((item) => item.groups || [])
    .find((item) => String(item.id) === groupId);
  const parentType =
    type || app.taxonomy.find((item) => item.id === group?.doc_type_id);
  return {
    docTypeId: parentType?.id || null,
    groupId: groupId ? Number(groupId) : null,
    buttonLabel: group
      ? `${parentType?.name || "Tài liệu"} › ${group.name}`
      : parentType?.name || "Tất cả tài liệu",
    label: group
      ? `${parentType?.name || "Tài liệu"} › ${group.name}`
      : parentType?.name || "Tất cả tài liệu đang sử dụng",
  };
}

function updateScopeSummary() {
  $("scopeSummary").textContent = selectedScope().buttonLabel;
}

function setScopeExpanded(expanded) {
  $("scopeToggle").setAttribute("aria-expanded", String(expanded));
  $("scopeControls").hidden = !expanded;
}

function buildHistory(messages) {
  const values = messages
    .filter(
      (message) =>
        ["user", "assistant"].includes(message.role) && message.content,
    )
    .slice(-12)
    .map(({ role, content }) => ({ role, content }));
  let total = values.reduce((sum, message) => sum + message.content.length, 0);
  while (values.length && total > 24000) total -= values.shift().content.length;
  return values;
}

async function generateResponse() {
  const chat = currentChat();
  if (!chat || app.busy) return;
  const userIndex = chat.messages.findLastIndex(
    (message) => message.role === "user",
  );
  if (userIndex < 0) return;
  const userMessage = chat.messages[userIndex];
  userMessage.id ||= newId();
  const question = userMessage.content;
  const scope = selectedScope();
  const hasDocumentScope = Boolean(scope.docTypeId || scope.groupId);
  const dataSource = hasDocumentScope ? "documents" : "auto";
  const payload = {
    query: question,
    history: buildHistory(chat.messages.slice(0, userIndex)),
    data_source: dataSource,
    conversation_id: chat.id,
    conversation_title: chat.title,
    message_id: userMessage.id,
  };
  if (DEBUG_MODE && app.prefs.aiProvider) {
    payload.ai_provider = app.prefs.aiProvider;
  }
  if (hasDocumentScope) {
    if (scope.docTypeId) payload.doc_type_id = scope.docTypeId;
    if (scope.groupId) payload.group_ids = [scope.groupId];
  }

  app.controller = new AbortController();
  setBusy(true);
  try {
    const result = await sendChat(payload, app.controller.signal);
    const resolvedSource = result.data_source || "documents";
    userMessage.id = result.user_message_id || userMessage.id;
    chat.messages.push({
      id: result.assistant_message_id || newId(),
      role: "assistant",
      content: result.answer,
      dataSource: resolvedSource,
      sources: result.sources || [],
      productSources: result.product_sources || [],
      productResult: result.product_result || null,
      retrievedContent: result.retrieved_content || "",
      query: question,
      scope: resolvedSource === "documents" ? scope.label : "Kho sản phẩm",
      createdAt: new Date().toISOString(),
    });
    chat.persisted = true;
    chat.updatedAt = new Date().toISOString();
    storeChats();
  } catch (error) {
    if (error?.name !== "AbortError") {
      chat.messages.push({
        role: "assistant",
        content: `Không thể lấy câu trả lời lúc này. ${error?.message || "Vui lòng thử lại."}`,
        dataSource: dataSource === "auto" ? "documents" : dataSource,
        sources: [],
        productSources: [],
        productResult: null,
        createdAt: new Date().toISOString(),
      });
      storeChats();
      toast(error?.message || "Yêu cầu thất bại");
    }
  } finally {
    app.controller = null;
    setBusy(false);
    renderHistory();
    $("messageInput").focus();
  }
}

function stopGeneration() {
  app.controller?.abort();
  app.controller = null;
  setBusy(false);
  toast("Đã dừng yêu cầu");
}

async function retryMessage(index) {
  if (app.busy) return;
  const chat = currentChat();
  if (!chat || chat.messages[index]?.role !== "assistant") return;
  const userIndex = chat.messages
    .slice(0, index)
    .findLastIndex((message) => message.role === "user");
  if (userIndex < 0) return;
  chat.messages = chat.messages.slice(0, userIndex + 1);
  chat.messages[userIndex].id ||= newId();
  storeChats();
  renderMessages({ scroll: true });
  await generateResponse();
}

async function submitMessage(value) {
  const content = String(value || "").trim();
  if (!content || app.busy) return;
  let chat = currentChat();
  if (!chat) {
    startNewChat();
    chat = currentChat();
  }
  chat.messages.push({
    id: newId(),
    role: "user",
    content,
    dataSource: "auto",
    createdAt: new Date().toISOString(),
  });
  if (chat.messages.filter((message) => message.role === "user").length === 1) {
    chat.title = content.length > 55 ? `${content.slice(0, 52)}…` : content;
  }
  chat.updatedAt = new Date().toISOString();
  $("messageInput").value = "";
  resizeComposer();
  storeChats();
  renderHistory();
  renderMessages({ scroll: true });
  await generateResponse();
}

function formatFileSize(size) {
  if (!Number.isFinite(size) || size <= 0) return "";
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function createImageThumbnail(file, maxEdge = 480) {
  return new Promise((resolve, reject) => {
    const sourceUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      try {
        const scale = Math.min(
          1,
          maxEdge / Math.max(image.width, image.height),
        );
        const width = Math.max(1, Math.round(image.width * scale));
        const height = Math.max(1, Math.round(image.height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, width, height);
        context.drawImage(image, 0, 0, width, height);
        resolve(canvas.toDataURL("image/jpeg", 0.78));
      } catch (error) {
        reject(error);
      } finally {
        URL.revokeObjectURL(sourceUrl);
      }
    };
    image.onerror = () => {
      URL.revokeObjectURL(sourceUrl);
      reject(new Error("Không thể tạo ảnh xem trước."));
    };
    image.src = sourceUrl;
  });
}

function clearProductImage() {
  if (app.productImagePreviewUrl) {
    URL.revokeObjectURL(app.productImagePreviewUrl);
  }
  app.productImageFile = null;
  app.productImagePreviewUrl = "";
  $("productImageInput").value = "";
  $("productImagePreviewImage").removeAttribute("src");
  $("productImagePreview").classList.add("hidden");
  requestAnimationFrame(updateComposerDockHeight);
}

function selectProductImage(file) {
  if (!file) return;
  const supported = new Set(["image/jpeg", "image/png", "image/webp"]);
  if (!supported.has(file.type)) {
    clearProductImage();
    toast("Chỉ hỗ trợ ảnh JPEG, PNG và WebP.");
    return;
  }
  clearProductImage();
  app.productImageFile = file;
  app.productImagePreviewUrl = URL.createObjectURL(file);
  $("productImagePreviewImage").src = app.productImagePreviewUrl;
  $("productImagePreviewName").textContent = file.name;
  $("productImagePreviewMeta").textContent = [
    file.type,
    formatFileSize(file.size),
  ]
    .filter(Boolean)
    .join(" · ");
  $("productImagePreview").classList.remove("hidden");
  $("messageInput").placeholder = "Có thể nhập thêm mô tả cho ảnh sản phẩm...";
  requestAnimationFrame(updateComposerDockHeight);
}

async function submitProductImage(value) {
  const file = app.productImageFile;
  if (!file || app.busy) return;
  const content =
    String(value || "").trim() || "Nhận diện sản phẩm bằng hình ảnh";
  let attachmentPreview = "";
  try {
    attachmentPreview = await createImageThumbnail(file);
  } catch {
    // Tên tệp vẫn được hiển thị nếu trình duyệt không tạo được thumbnail.
  }
  let chat = currentChat();
  if (!chat) {
    startNewChat();
    chat = currentChat();
  }
  const userMessage = {
    id: newId(),
    role: "user",
    content,
    attachmentName: file.name,
    attachmentPreview,
    dataSource: "products",
    createdAt: new Date().toISOString(),
  };
  chat.messages.push(userMessage);
  if (chat.messages.filter((message) => message.role === "user").length === 1) {
    chat.title = `Tìm bằng ảnh · ${file.name}`.slice(0, 55);
  }
  chat.updatedAt = new Date().toISOString();
  $("messageInput").value = "";
  clearProductImage();
  syncDataSource();
  resizeComposer();
  storeChats();
  renderHistory();
  renderMessages({ scroll: true });

  app.controller = new AbortController();
  setBusy(true);
  try {
    try {
      await persistClientMessage(chat, userMessage);
    } catch (error) {
      toast(`Chưa lưu được câu hỏi: ${error.message}`);
    }

    const result = await searchProductsByImage(file, app.controller.signal);
    const products = Array.isArray(result.products) ? result.products : [];
    const identifiedProducts = products.slice(0, 1);
    const assistantMessage = {
      id: newId(),
      role: "assistant",
      content: buildImageSearchAnswer(result, identifiedProducts),
      dataSource: "products",
      sources: [],
      productSources: identifiedProducts,
      productResult: {
        page: 1,
        page_size: identifiedProducts.length || 1,
        shown: identifiedProducts.length,
        total: identifiedProducts.length,
        total_pages: identifiedProducts.length ? 1 : 0,
        has_more: false,
      },
      imageSearch: true,
      imageSearchLowConfidence: Boolean(result.low_confidence),
      createdAt: new Date().toISOString(),
    };
    chat.messages.push(assistantMessage);
    try {
      await persistClientMessage(chat, assistantMessage);
    } catch (error) {
      toast(`Chưa lưu được kết quả: ${error.message}`);
    }
    chat.updatedAt = new Date().toISOString();
    storeChats();
  } catch (error) {
    if (error?.name !== "AbortError") {
      const errorMessage = {
        id: newId(),
        role: "assistant",
        content: `Không thể tìm sản phẩm bằng ảnh lúc này. ${error?.message || "Vui lòng thử lại."}`,
        dataSource: "products",
        sources: [],
        productSources: [],
        productResult: null,
        imageSearch: true,
        createdAt: new Date().toISOString(),
      };
      chat.messages.push(errorMessage);
      try {
        await persistClientMessage(chat, errorMessage);
      } catch {}
      storeChats();
      toast(error?.message || "Tìm sản phẩm bằng ảnh thất bại");
    }
  } finally {
    app.controller = null;
    setBusy(false);
    renderHistory();
    $("messageInput").focus();
  }
}

function submitComposer() {
  if (app.productImageFile) {
    return submitProductImage($("messageInput").value);
  }
  return submitMessage($("messageInput").value);
}

function resizeComposer() {
  const input = $("messageInput");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 195)}px`;
  requestAnimationFrame(updateComposerDockHeight);
}

function fillSelect(select, items, allLabel) {
  const previous = select.value;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = allLabel;
  select.append(all);
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === previous))
    select.value = previous;
}

function groupsForType(typeId) {
  if (!typeId) return app.taxonomy.flatMap((item) => item.groups || []);
  return (
    app.taxonomy.find((item) => String(item.id) === String(typeId))?.groups ||
    []
  );
}

function syncGroupSelects() {
  fillSelect(
    $("chatDocumentGroup"),
    groupsForType($("chatDocumentType").value),
    "Tất cả nhóm",
  );
  fillSelect(
    $("documentGroupFilter"),
    groupsForType($("documentTypeFilter").value),
    "Tất cả nhóm",
  );
  updateScopeSummary();
}

async function loadTaxonomy() {
  try {
    const result = await getTaxonomy();
    app.taxonomy = (result.doc_types || []).filter(
      (item) => item.is_active !== false,
    );
    fillSelect($("chatDocumentType"), app.taxonomy, "Tất cả loại");
    fillSelect($("documentTypeFilter"), app.taxonomy, "Tất cả loại");
    syncGroupSelects();
  } catch (error) {
    toast(`Không tải được bộ lọc: ${error.message}`);
  }
}

function documentTypeName(id) {
  return app.taxonomy.find((item) => item.id === id)?.name || "";
}

function documentGroupName(id) {
  return (
    app.taxonomy
      .flatMap((item) => item.groups || [])
      .find((item) => item.id === id)?.name || ""
  );
}

function renderDocuments() {
  const search = $("documentSearch").value.trim().toLocaleLowerCase("vi");
  const typeId = Number($("documentTypeFilter").value) || null;
  const groupId = Number($("documentGroupFilter").value) || null;
  const documents = app.documents.filter((item) => {
    const matchesSearch =
      !search ||
      `${item.title} ${item.description || ""} ${item.category || ""}`
        .toLocaleLowerCase("vi")
        .includes(search);
    return (
      matchesSearch &&
      (!typeId || item.doc_type_id === typeId) &&
      (!groupId || item.group_id === groupId)
    );
  });
  const container = $("documentList");
  container.replaceChildren();
  if (!documents.length) {
    const empty = document.createElement("p");
    empty.className = "drawer-loading";
    empty.textContent = app.documentsLoaded
      ? "Không tìm thấy tài liệu phù hợp."
      : "Đang tải tài liệu…";
    container.append(empty);
    return;
  }
  for (const item of documents) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "document-item";
    const image = document.createElement("span");
    image.className = "document-item-icon";
    image.append(icon("file"));
    const text = document.createElement("span");
    text.className = "document-item-text";
    const title = document.createElement("strong");
    title.textContent = item.title;
    const meta = document.createElement("small");
    meta.textContent = [
      documentTypeName(item.doc_type_id),
      documentGroupName(item.group_id),
      `${item.chunk_count || 0} đoạn`,
    ]
      .filter(Boolean)
      .join(" · ");
    text.append(title, meta);
    button.append(image, text, icon("chevron"));
    button.addEventListener("click", () => openDocument(item.id));
    container.append(button);
  }
}

async function ensureDocuments() {
  if (app.documentsLoaded) {
    renderDocuments();
    return;
  }
  renderDocuments();
  try {
    const result = await getDocuments();
    app.documents = result.documents || [];
    app.documentsLoaded = true;
    renderDocuments();
  } catch (error) {
    $("documentList").textContent = `Không tải được tài liệu: ${error.message}`;
  }
}

function showDocumentDialog(detail) {
  $("documentDialogTitle").textContent = detail.title || "Tài liệu";
  $("documentDialogMeta").textContent = [
    documentTypeName(detail.doc_type_id),
    documentGroupName(detail.group_id),
    detail.file_name,
  ]
    .filter(Boolean)
    .join(" · ");
  $("documentDialogState").textContent = detail.description || "";
  $("documentDialogContent").textContent =
    detail.content || "Tài liệu này không có nội dung văn bản để hiển thị.";
  $("documentDialog").showModal();
}

async function openDocument(id) {
  try {
    showDocumentDialog(await getDocument(id));
  } catch (error) {
    toast(`Không mở được tài liệu: ${error.message}`);
  }
}

async function openSourceDocument(source) {
  try {
    showDocumentDialog(await getDocumentBySourceKey(source.source_key));
  } catch (error) {
    toast(`Không mở được nguồn ${source.citation}: ${error.message}`);
  }
}

function permissionScopeLabel(scope) {
  if (scope.scope_type === "all") return "Toàn bộ tài liệu";
  if (scope.scope_type === "doc_type") {
    return (
      app.taxonomy.find((item) => String(item.id) === String(scope.doc_type_id))
        ?.name || `Loại #${scope.doc_type_id}`
    );
  }
  for (const docType of app.taxonomy) {
    const group = (docType.groups || []).find(
      (item) => String(item.id) === String(scope.doc_group_id),
    );
    if (group) return group.name;
  }
  return `Nhóm #${scope.doc_group_id}`;
}

function renderPermissionGroupTable() {
  const query = $("permissionGroupSearch")
    .value.trim()
    .toLocaleLowerCase("vi-VN");
  const groups = app.adminGroups.filter((group) =>
    [group.name, group.code, group.description]
      .filter(Boolean)
      .some((value) => value.toLocaleLowerCase("vi-VN").includes(query)),
  );
  const body = $("permissionGroupTableBody");
  body.replaceChildren();

  if (!groups.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.className = "permission-table-empty";
    cell.textContent = query
      ? "Không tìm thấy nhóm quyền phù hợp."
      : "Chưa có nhóm quyền nào.";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const group of groups) {
    const row = document.createElement("tr");

    const nameCell = document.createElement("td");
    const name = document.createElement("span");
    name.className = "permission-group-name";
    const code = document.createElement("small");
    code.textContent = group.code;
    const nameStrong = document.createElement("strong");
    nameStrong.textContent = group.name;
    name.append(code, nameStrong);
    nameCell.append(name);

    const descriptionCell = document.createElement("td");
    const description = document.createElement("span");
    description.className = "permission-table-description";
    description.textContent = group.description || "Chưa có mô tả";
    descriptionCell.append(description);

    const usersCell = document.createElement("td");
    usersCell.className = "permission-user-count";
    usersCell.textContent = String(group.user_count || 0);

    const scopesCell = document.createElement("td");
    const chips = document.createElement("div");
    chips.className = "permission-scope-chips";
    const labels = (group.scopes || []).map(permissionScopeLabel);
    const visibleLabels = labels.slice(0, 3);
    if (!visibleLabels.length) visibleLabels.push("Chưa cấp phạm vi");
    for (const label of visibleLabels) {
      const chip = document.createElement("span");
      chip.className = "permission-scope-chip";
      chip.textContent = label;
      chips.append(chip);
    }
    if (labels.length > visibleLabels.length) {
      const more = document.createElement("span");
      more.className = "permission-scope-chip";
      more.textContent = `+${labels.length - visibleLabels.length}`;
      chips.append(more);
    }
    scopesCell.append(chips);

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `permission-status${group.is_active ? "" : " inactive"}`;
    status.textContent = group.is_active ? "Đang hoạt động" : "Đã khóa";
    statusCell.append(status);

    const actionCell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "permission-row-actions";
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "permission-edit-button";
    editButton.title = `Chỉnh sửa ${group.name}`;
    editButton.setAttribute("aria-label", editButton.title);
    editButton.append(icon("edit"));
    editButton.addEventListener("click", () =>
      openPermissionGroupDialog(group),
    );
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "permission-row-delete-button";
    const deleteBlockReason = permissionGroupDeleteBlockReason(group);
    deleteButton.disabled = Boolean(deleteBlockReason);
    deleteButton.title = deleteBlockReason || `Xóa nhóm ${group.name}`;
    deleteButton.setAttribute("aria-label", deleteButton.title);
    deleteButton.append(icon("trash"));
    deleteButton.addEventListener("click", async () => {
      await deletePermissionGroupRecord(group, deleteButton);
    });

    actions.append(editButton, deleteButton);
    actionCell.append(actions);

    row.append(
      nameCell,
      descriptionCell,
      usersCell,
      scopesCell,
      statusCell,
      actionCell,
    );
    body.append(row);
  }
}

function permissionUserStatusLabel(status) {
  if (status === "active") return "Hoạt động";
  if (status === "locked") return "Đã khóa";
  return "Vô hiệu hóa";
}

function populatePermissionUserDepartmentFilter() {
  const select = $("permissionDepartmentFilter");
  const selected = select.value;
  const departments = [
    ...new Set(app.adminUsers.map((user) => user.department).filter(Boolean)),
  ].sort((left, right) => left.localeCompare(right, "vi-VN"));
  select.replaceChildren(new Option("Tất cả phòng ban", ""));
  for (const department of departments) {
    select.append(new Option(department, department));
  }
  select.value = departments.includes(selected) ? selected : "";
}

function renderPermissionUsers() {
  const query = $("permissionUserSearch")
    .value.trim()
    .toLocaleLowerCase("vi-VN");
  const department = $("permissionDepartmentFilter").value;
  const statusFilter = $("permissionStatusFilter").value;
  const users = app.adminUsers.filter((user) => {
    const matchesQuery = [
      user.full_name,
      user.username,
      user.email,
      user.department,
      user.permission_group_name,
    ]
      .filter(Boolean)
      .some((value) => value.toLocaleLowerCase("vi-VN").includes(query));
    return (
      matchesQuery &&
      (!department || user.department === department) &&
      (!statusFilter || user.account_status === statusFilter)
    );
  });

  $("permissionUserTotal").textContent = `${app.adminUsers.length} người dùng`;
  $("permissionUserResultCount").textContent =
    `Hiển thị ${users.length} trong tổng số ${app.adminUsers.length} người dùng`;

  const body = $("permissionUserList");
  body.replaceChildren();
  if (!users.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "permission-table-empty";
    cell.textContent = "Không tìm thấy người dùng phù hợp.";
    row.append(cell);
    body.append(row);
    return;
  }

  for (const user of users) {
    const row = document.createElement("tr");

    const userCell = document.createElement("td");
    const info = document.createElement("div");
    info.className = "permission-user-identity";
    const avatar = document.createElement("span");
    avatar.className = "permission-user-avatar";
    avatar.textContent = accountInitials(user);
    const copy = document.createElement("span");
    copy.className = "permission-user-copy";
    const name = document.createElement("strong");
    name.textContent = user.full_name;
    const email = document.createElement("small");
    email.textContent = user.email || "Chưa có email";
    copy.append(name, email);
    info.append(avatar, copy);
    userCell.append(info);

    const usernameCell = document.createElement("td");
    const username = document.createElement("code");
    username.className = "permission-username";
    username.textContent = user.username;
    usernameCell.append(username);

    const departmentCell = document.createElement("td");
    departmentCell.textContent = user.department || "—";

    const groupCell = document.createElement("td");
    const groupInfo = document.createElement("span");
    groupInfo.className = "permission-user-group";
    if (user.role === "admin") {
      const code = document.createElement("small");
      code.textContent = "ADMIN";
      const groupName = document.createElement("strong");
      groupName.textContent = "Toàn quyền quản trị";
      groupInfo.append(code, groupName);
    } else {
      const group = app.adminGroups.find(
        (item) => String(item.id) === String(user.permission_group_id || ""),
      );
      const code = document.createElement("small");
      code.textContent = group?.code || "CHƯA_GÁN";
      const groupName = document.createElement("strong");
      groupName.textContent = group?.name || "Chưa gán nhóm";
      groupInfo.append(code, groupName);
    }
    groupCell.append(groupInfo);

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `permission-user-status ${user.account_status}`;
    status.textContent = permissionUserStatusLabel(user.account_status);
    statusCell.append(status);

    const lastLoginCell = document.createElement("td");
    lastLoginCell.className = "permission-user-last-login";
    lastLoginCell.textContent = formatAdminDateTime(user.last_login_at);

    const actionCell = document.createElement("td");
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "permission-edit-button";
    editButton.title = `Chỉnh sửa người dùng ${user.full_name}`;
    editButton.setAttribute("aria-label", editButton.title);
    editButton.append(icon("edit"));
    editButton.addEventListener("click", () => openPermissionUserDialog(user));
    actionCell.append(editButton);

    row.append(
      userCell,
      usernameCell,
      departmentCell,
      groupCell,
      statusCell,
      lastLoginCell,
      actionCell,
    );
    body.append(row);
  }
}

function renderPermissionUserGroupChoices() {
  const user = app.adminUsers.find(
    (item) => item.id === app.adminEditingUserId,
  );
  const container = $("permissionUserGroupList");
  container.replaceChildren();
  if (!user) return;

  const query = $("permissionUserGroupSearch")
    .value.trim()
    .toLocaleLowerCase("vi-VN");
  const groups = app.adminGroups.filter((group) => {
    const isCurrent = String(group.id) === String(user.permission_group_id || "");
    const matches = [group.code, group.name, group.description]
      .filter(Boolean)
      .some((value) => value.toLocaleLowerCase("vi-VN").includes(query));
    return (group.is_active || isCurrent) && matches;
  });

  if (!query) {
    const label = document.createElement("label");
    label.className = "permission-user-group-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "permission_user_group";
    input.value = "";
    input.checked = !user.permission_group_id;
    const copy = document.createElement("span");
    const code = document.createElement("small");
    code.textContent = "CHƯA_GÁN";
    const name = document.createElement("strong");
    name.textContent = "Chưa gán nhóm";
    copy.append(code, name);
    const meta = document.createElement("small");
    meta.textContent = "Không có quyền xem tài liệu";
    label.append(input, copy, meta);
    container.append(label);
  }

  for (const group of groups) {
    const label = document.createElement("label");
    label.className = "permission-user-group-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "permission_user_group";
    input.value = group.id;
    input.checked = String(group.id) === String(user.permission_group_id || "");
    const copy = document.createElement("span");
    const code = document.createElement("small");
    code.textContent = group.code;
    const name = document.createElement("strong");
    name.textContent = group.name;
    copy.append(code, name);
    const meta = document.createElement("small");
    meta.textContent = group.is_active
      ? `${group.scopes?.length || 0} phạm vi`
      : "Nhóm đã khóa";
    label.append(input, copy, meta);
    container.append(label);
  }

  if (!container.children.length) {
    const empty = document.createElement("p");
    empty.className = "permission-table-empty";
    empty.textContent = "Không tìm thấy nhóm quyền.";
    container.append(empty);
  }
  syncPermissionUserRoleControls();
}

function openPermissionUserDialog(user) {
  if (!user) return;
  app.adminEditingUserId = user.id;
  $("permissionUserDialogAvatar").textContent = accountInitials(user);
  $("permissionUserDialogName").textContent = user.full_name;
  $("permissionUserDialogRole").textContent = accountRoleLabel(user.role);
  $("permissionUserFullName").value = user.full_name;
  $("permissionUserUsername").value = user.username;
  $("permissionUserEmail").value = user.email || "";
  $("permissionUserDepartment").value = user.department || "";
  $("permissionUserRole").value = user.role;
  $("permissionUserActive").checked = user.account_status === "active";
  $("permissionUserGroupSearch").value = "";
  setPermissionPasswordResetExpanded(false);
  renderPermissionUserGroupChoices();
  syncPermissionUserStatusControl();
  $("permissionUserDialog").showModal();
  $("permissionUserFullName").focus();
}

function closePermissionUserDialog() {
  if ($("permissionUserDialog").open) $("permissionUserDialog").close();
  app.adminEditingUserId = "";
}

function setPermissionUserDialogBusy(busy) {
  $("permissionUserForm")
    .querySelectorAll("input, select, button")
    .forEach((control) => (control.disabled = busy));
  $("savePermissionUserButton").textContent = busy
    ? "Đang lưu..."
    : "Lưu thay đổi";
  if (!busy) {
    syncPermissionUserRoleControls();
    syncPermissionUserStatusControl();
  }
}

function syncPermissionUserStatusControl() {
  const user = app.adminUsers.find(
    (item) => item.id === app.adminEditingUserId,
  );
  const input = $("permissionUserActive");
  const active = input.checked;
  input.disabled = Boolean(user && user.id === app.currentUser?.id);
  $("permissionUserDialogStatus").textContent = active
    ? "Tài khoản đang hoạt động"
    : "Tài khoản đã bị vô hiệu hóa";
  $("permissionUserStatusHint").textContent = input.disabled
    ? "Không thể tự vô hiệu hóa tài khoản đang đăng nhập."
    : active
      ? "Người dùng có thể đăng nhập và sử dụng hệ thống."
      : "Người dùng sẽ bị ngừng truy cập ngay sau khi lưu.";
}

function syncPermissionUserRoleControls() {
  const isAdmin = $("permissionUserRole").value === "admin";
  $("permissionUserDialogRole").textContent = accountRoleLabel(
    $("permissionUserRole").value,
  );
  $("permissionUserGroupSearch").disabled = isAdmin;
  $("permissionUserGroupList").classList.toggle("is-disabled", isAdmin);
  $("permissionUserGroupList")
    .querySelectorAll('input[name="permission_user_group"]')
    .forEach((input) => (input.disabled = isAdmin));
  $("permissionUserGroupHint").textContent = isAdmin
    ? "Admin có toàn quyền quản trị và không phụ thuộc nhóm tài liệu."
    : "Mỗi người dùng chỉ thuộc một nhóm quyền tại một thời điểm.";
}

function setPermissionPasswordResetExpanded(expanded) {
  const panel = $("permissionPasswordResetPanel");
  const button = $("togglePermissionPasswordResetButton");
  panel.classList.toggle("hidden", !expanded);
  button.setAttribute("aria-expanded", String(expanded));
  if (!expanded) {
    $("permissionNewPassword").value = "";
    $("permissionConfirmPassword").value = "";
  }
}

function setPermissionPasswordResetBusy(busy) {
  $("permissionUserForm")
    .querySelectorAll("input, select, button")
    .forEach((control) => (control.disabled = busy));
  $("confirmPermissionPasswordResetButton").textContent = busy
    ? "Đang đặt lại..."
    : "Xác nhận đặt lại";
  if (!busy) {
    syncPermissionUserRoleControls();
    syncPermissionUserStatusControl();
  }
}

async function submitPermissionPasswordReset() {
  const user = app.adminUsers.find(
    (item) => item.id === app.adminEditingUserId,
  );
  if (!user) return;
  const newPassword = $("permissionNewPassword").value;
  const confirmation = $("permissionConfirmPassword").value;
  if (newPassword.length < 4) {
    toast("Mật khẩu mới phải có ít nhất 4 ký tự.");
    $("permissionNewPassword").focus();
    return;
  }
  if (newPassword !== confirmation) {
    toast("Mật khẩu xác nhận không khớp.");
    $("permissionConfirmPassword").focus();
    return;
  }

  setPermissionPasswordResetBusy(true);
  try {
    await resetAdminUserPassword(user.id, newPassword);
    const resetCurrentAccount = user.id === app.currentUser?.id;
    setPermissionPasswordResetExpanded(false);
    if (resetCurrentAccount) {
      closePermissionUserDialog();
      syncAuthenticatedUser(null);
      openLoginDialog({ required: true });
      setLoginMessage("Đã đặt lại mật khẩu. Vui lòng đăng nhập lại.");
      return;
    }
    toast(`Đã đặt lại mật khẩu cho ${user.full_name}`);
  } catch (error) {
    toast(`Không thể đặt lại mật khẩu: ${error.message}`);
  } finally {
    setPermissionPasswordResetBusy(false);
  }
}

async function submitPermissionUserDialog() {
  const user = app.adminUsers.find(
    (item) => item.id === app.adminEditingUserId,
  );
  if (!user) return;
  const selected = $("permissionUserGroupList").querySelector(
    'input[name="permission_user_group"]:checked',
  );
  const nextGroupId = selected?.value || null;
  const role = $("permissionUserRole").value;
  const payload = {
    username: $("permissionUserUsername").value.trim(),
    full_name: $("permissionUserFullName").value.trim(),
    email: $("permissionUserEmail").value.trim() || null,
    department: $("permissionUserDepartment").value.trim() || null,
    role,
    account_status: $("permissionUserActive").checked
      ? "active"
      : "disabled",
    permission_group_id: role === "admin" ? null : nextGroupId,
  };

  setPermissionUserDialogBusy(true);
  try {
    const updatedUser = await updateAdminUser(user.id, payload);
    if (user.id === app.currentUser?.id) {
      syncAuthenticatedUser({ ...app.currentUser, ...updatedUser });
    }
    closePermissionUserDialog();
    await ensureAdminData(true);
    toast(`Đã cập nhật người dùng ${updatedUser.full_name}`);
  } catch (error) {
    toast(`Không thể cập nhật người dùng: ${error.message}`);
  } finally {
    setPermissionUserDialogBusy(false);
  }
}

function populateCreateUserPermissionGroups() {
  const select = $("createUserPermissionGroup");
  select.replaceChildren(new Option("Chưa gán nhóm", ""));
  const activeGroups = app.adminGroups
    .filter((group) => group.is_active)
    .sort((left, right) => left.name.localeCompare(right.name, "vi-VN"));
  for (const group of activeGroups) {
    select.append(new Option(`${group.code} — ${group.name}`, group.id));
  }
}

function openCreatePermissionUserDialog() {
  const form = $("createPermissionUserForm");
  form.reset();
  populateCreateUserPermissionGroups();
  $("createUserRole").value = "employee";
  $("createUserStatus").value = "active";
  $("createPermissionUserDialog").showModal();
  $("createUserFullName").focus();
}

function closeCreatePermissionUserDialog() {
  if ($("createPermissionUserDialog").open) {
    $("createPermissionUserDialog").close();
  }
}

function setCreatePermissionUserBusy(busy) {
  const form = $("createPermissionUserForm");
  form
    .querySelectorAll("input, select, button")
    .forEach((control) => (control.disabled = busy));
  $("saveCreatePermissionUserButton").textContent = busy
    ? "Đang tạo..."
    : "Tạo người dùng";
}

async function submitCreatePermissionUserDialog() {
  const payload = {
    full_name: $("createUserFullName").value.trim(),
    username: $("createUserUsername").value.trim(),
    password: $("createUserPassword").value,
    email: $("createUserEmail").value.trim() || null,
    department: $("createUserDepartment").value.trim() || null,
    role: $("createUserRole").value,
    account_status: $("createUserStatus").value,
    permission_group_id: $("createUserPermissionGroup").value || null,
  };

  setCreatePermissionUserBusy(true);
  try {
    const user = await createAdminUser(payload);
    closeCreatePermissionUserDialog();
    await ensureAdminData(true);
    toast(`Đã tạo người dùng ${user.full_name}`);
  } catch (error) {
    toast(`Không thể tạo người dùng: ${error.message}`);
  } finally {
    setCreatePermissionUserBusy(false);
  }
}

function updatePermissionDialogScopeControls() {
  const tree = $("permissionDialogScopeTree");
  const all = tree.querySelector('[data-scope="all"]');
  const allChecked = Boolean(all?.checked);
  tree.querySelectorAll('[data-scope="doc_type"]').forEach((typeInput) => {
    typeInput.disabled = allChecked;
    typeInput
      .closest(".admin-scope-type-row")
      ?.querySelectorAll('[data-scope="doc_group"]')
      .forEach((groupInput) => {
        groupInput.disabled = allChecked || typeInput.checked;
      });
  });
  const selected = collectPermissionDialogScopes();
  $("permissionDialogScopeCount").textContent = `${selected.length} mục`;
}

function renderPermissionDialogScopes(scopes = []) {
  const tree = $("permissionDialogScopeTree");
  tree.replaceChildren();
  const hasAll = scopes.some((scope) => scope.scope_type === "all");
  const typeIds = new Set(
    scopes
      .filter((scope) => scope.scope_type === "doc_type")
      .map((scope) => String(scope.doc_type_id)),
  );
  const groupIds = new Set(
    scopes
      .filter((scope) => scope.scope_type === "doc_group")
      .map((scope) => String(scope.doc_group_id)),
  );

  const allLabel = document.createElement("label");
  allLabel.className = "admin-scope-all";
  const allInput = document.createElement("input");
  allInput.type = "checkbox";
  allInput.dataset.scope = "all";
  allInput.checked = hasAll;
  allLabel.append(
    allInput,
    document.createTextNode("Cho phép xem toàn bộ tài liệu"),
  );
  tree.append(allLabel);

  for (const docType of app.taxonomy) {
    const row = document.createElement("div");
    row.className = "admin-scope-type-row";
    const typeLabel = document.createElement("label");
    typeLabel.className = "admin-scope-type";
    const typeInput = document.createElement("input");
    typeInput.type = "checkbox";
    typeInput.dataset.scope = "doc_type";
    typeInput.dataset.id = String(docType.id);
    typeInput.checked = typeIds.has(String(docType.id));
    typeLabel.append(typeInput, document.createTextNode(docType.name));
    row.append(typeLabel);

    const children = document.createElement("div");
    children.className = "admin-scope-groups";
    for (const documentGroup of docType.groups || []) {
      const label = document.createElement("label");
      label.className = "admin-scope-group";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.scope = "doc_group";
      input.dataset.id = String(documentGroup.id);
      input.checked = groupIds.has(String(documentGroup.id));
      const text = document.createElement("span");
      text.textContent = documentGroup.name;
      label.append(input, text);
      children.append(label);
    }
    row.append(children);
    tree.append(row);
  }

  tree.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (input.dataset.scope === "all" && input.checked) {
        tree
          .querySelectorAll('input[type="checkbox"]:not([data-scope="all"])')
          .forEach((item) => {
            item.checked = false;
          });
      }
      if (input.dataset.scope === "doc_type" && input.checked) {
        input
          .closest(".admin-scope-type-row")
          ?.querySelectorAll('[data-scope="doc_group"]')
          .forEach((item) => {
            item.checked = false;
          });
      }
      updatePermissionDialogScopeControls();
    });
  });
  updatePermissionDialogScopeControls();
}

function collectPermissionDialogScopes() {
  const tree = $("permissionDialogScopeTree");
  if (tree.querySelector('[data-scope="all"]:checked')) {
    return [{ scope_type: "all", doc_type_id: null, doc_group_id: null }];
  }
  const scopes = new Map();
  for (const input of tree.querySelectorAll('input[type="checkbox"]:checked')) {
    const id = Number(input.dataset.id);
    if (!Number.isSafeInteger(id) || id < 1) continue;
    if (input.dataset.scope === "doc_type") {
      scopes.set(`type:${id}`, {
        scope_type: "doc_type",
        doc_type_id: id,
        doc_group_id: null,
      });
    } else if (
      input.dataset.scope === "doc_group" &&
      !input
        .closest(".admin-scope-type-row")
        ?.querySelector('[data-scope="doc_type"]:checked')
    ) {
      scopes.set(`group:${id}`, {
        scope_type: "doc_group",
        doc_type_id: null,
        doc_group_id: id,
      });
    }
  }
  return [...scopes.values()];
}

function renderPermissionDialogUsers(group = null) {
  const container = $("permissionDialogUserList");
  container.replaceChildren();

  if (!group) {
    $("permissionDialogUserCount").textContent = "Chưa có người dùng";
    const empty = document.createElement("p");
    empty.className = "permission-dialog-user-empty";
    empty.textContent = "Lưu nhóm trước để gán người dùng.";
    container.append(empty);
    return;
  }

  const users = app.adminUsers.filter(
    (user) => String(user.permission_group_id || "") === String(group.id),
  );
  $("permissionDialogUserCount").textContent = `${users.length} người dùng`;

  if (!users.length) {
    const empty = document.createElement("p");
    empty.className = "permission-dialog-user-empty";
    empty.textContent = "Nhóm này chưa có người dùng.";
    container.append(empty);
    return;
  }

  for (const user of users) {
    const row = document.createElement("div");
    row.className = "permission-dialog-user";

    const avatar = document.createElement("span");
    avatar.className = "permission-dialog-user-avatar";
    avatar.textContent = accountInitials(user);

    const info = document.createElement("span");
    info.className = "permission-dialog-user-info";
    const name = document.createElement("strong");
    name.textContent = user.full_name;
    const meta = document.createElement("small");
    meta.textContent = [
      `@${user.username}`,
      user.department,
      accountRoleLabel(user.role),
    ]
      .filter(Boolean)
      .join(" · ");
    info.append(name, meta);

    const status = document.createElement("span");
    status.className = `permission-dialog-user-status ${user.account_status}`;
    status.textContent =
      user.account_status === "active"
        ? "Hoạt động"
        : user.account_status === "locked"
          ? "Đã khóa"
          : "Vô hiệu hóa";

    row.append(avatar, info, status);
    container.append(row);
  }
}

function syncDeletePermissionGroupButton(group = null, busy = false) {
  const button = $("deletePermissionGroupButton");

  button.classList.toggle("hidden", !group);

  if (!group) {
    button.disabled = true;
    button.title = "";
    return;
  }

  const blockReason = permissionGroupDeleteBlockReason(group);
  button.disabled = busy || Boolean(blockReason);
  button.title = blockReason || `Xóa nhóm ${group.code}`;
}

function permissionGroupDeleteBlockReason(group) {
  if (group.code?.toUpperCase() === "ALL_DOCUMENTS") {
    return "Không thể xóa nhóm quyền hệ thống.";
  }
  if (Number(group.user_count || 0) > 0) {
    return (
      `Nhóm đang có ${group.user_count} người dùng. ` +
      "Hãy chuyển họ sang nhóm khác trước."
    );
  }
  return "";
}
function openPermissionGroupDialog(group = null) {
  app.adminEditingGroupId = group?.id || "";
  $("permissionGroupForm").reset();
  $("permissionDialogTitle").textContent = group
    ? "Chỉnh sửa nhóm quyền"
    : "Tạo nhóm quyền";
  $("permissionDialogDescription").textContent = group
    ? "Cập nhật thông tin nhóm và phạm vi tài liệu được phép truy cập."
    : "Thiết lập thông tin nhóm và phạm vi tài liệu được phép truy cập.";
  $("permissionGroupName").value = group?.name || "";
  $("permissionGroupCode").value = group?.code || "";
  $("permissionGroupCode").readOnly = Boolean(group);
  $("permissionGroupCodeHint").textContent = group
    ? "Mã nhóm không thể thay đổi sau khi tạo."
    : "Chỉ dùng chữ không dấu, số, dấu gạch ngang hoặc gạch dưới.";
  $("permissionGroupDescription").value = group?.description || "";
  $("permissionDescriptionCount").textContent = String(
    $("permissionGroupDescription").value.length,
  );
  $("permissionGroupActive").checked = group ? group.is_active : true;
  $("assignUsersFromDialogButton").disabled = !group;
  $("savePermissionGroupButton").textContent = group
    ? "Lưu thay đổi"
    : "Tạo nhóm";
  syncDeletePermissionGroupButton(group);
  renderPermissionDialogUsers(group);
  renderPermissionDialogScopes(group?.scopes || []);
  $("permissionGroupDialog").showModal();
  $(group ? "permissionGroupName" : "permissionGroupCode").focus();
}

function closePermissionGroupDialog() {
  if ($("permissionGroupDialog").open) $("permissionGroupDialog").close();
  app.adminEditingGroupId = "";
}

function setPermissionDialogBusy(busy) {
  $("savePermissionGroupButton").disabled = busy;
  $("cancelPermissionDialogButton").disabled = busy;
  $("closePermissionDialogButton").disabled = busy;
  const currentGroup = app.adminGroups.find(
    (group) => group.id === app.adminEditingGroupId,
  );
  syncDeletePermissionGroupButton(currentGroup || null, busy);
  $("savePermissionGroupButton").textContent = busy
    ? "Đang lưu..."
    : app.adminEditingGroupId
      ? "Lưu thay đổi"
      : "Tạo nhóm";
}

async function deletePermissionGroupRecord(group, triggerButton = null) {
  if (!group) return;

  const blockReason = permissionGroupDeleteBlockReason(group);
  if (blockReason) {
    toast(blockReason);
    return;
  }

  const confirmed = window.confirm(
    `Bạn có chắc muốn xóa nhóm quyền?\n\n` +
      `${group.code} — ${group.name}\n\n` +
      "Toàn bộ phạm vi tài liệu của nhóm cũng sẽ bị xóa. " +
      "Hành động này không thể hoàn tác.",
  );
  if (!confirmed) return;

  const dialogWasOpen = $("permissionGroupDialog").open;
  if (dialogWasOpen) setPermissionDialogBusy(true);
  if (triggerButton) {
    triggerButton.disabled = true;
    triggerButton.setAttribute("aria-busy", "true");
  }
  try {
    const result = await deletePermissionGroup(group.id);
    if (dialogWasOpen) closePermissionGroupDialog();
    await ensureAdminData(true);
    toast(result.message || `Đã xóa nhóm ${group.name}.`);
  } catch (error) {
    toast(`Không thể xóa nhóm quyền: ${error.message}`);
  } finally {
    if (dialogWasOpen) setPermissionDialogBusy(false);
    if (triggerButton?.isConnected) {
      triggerButton.disabled = false;
      triggerButton.removeAttribute("aria-busy");
    }
  }
}

async function deleteEditingPermissionGroup() {
  const group = app.adminGroups.find(
    (item) => item.id === app.adminEditingGroupId,
  );
  await deletePermissionGroupRecord(group);
}

async function submitPermissionGroupDialog() {
  const payload = {
    name: $("permissionGroupName").value.trim(),
    description: $("permissionGroupDescription").value.trim() || null,
  };
  const scopes = collectPermissionDialogScopes();
  setPermissionDialogBusy(true);
  try {
    if (app.adminEditingGroupId) {
      await updatePermissionGroup(app.adminEditingGroupId, {
        ...payload,
        is_active: $("permissionGroupActive").checked,
      });
      await updatePermissionScopes(app.adminEditingGroupId, scopes);
      toast("Đã cập nhật nhóm quyền");
    } else {
      const created = await createPermissionGroup({
        ...payload,
        code: $("permissionGroupCode").value.trim().toUpperCase(),
      });
      if (!$("permissionGroupActive").checked) {
        await updatePermissionGroup(created.id, {
          ...payload,
          is_active: false,
        });
      }
      await updatePermissionScopes(created.id, scopes);
      toast(`Đã tạo nhóm ${created.name}`);
    }
    closePermissionGroupDialog();
    await ensureAdminData(true);
  } catch (error) {
    toast(`Không thể lưu nhóm quyền: ${error.message}`);
  } finally {
    setPermissionDialogBusy(false);
  }
}

async function ensureAdminData(force = false) {
  if (app.currentUser?.role !== "admin") return;
  if (app.adminLoaded && !force) {
    renderPermissionGroupTable();
    populatePermissionUserDepartmentFilter();
    renderPermissionUsers();
    return;
  }
  try {
    const [groupsResult, usersResult] = await Promise.all([
      getPermissionGroups(),
      getAdminUsers(),
    ]);
    app.adminGroups = groupsResult.groups || [];
    app.adminUsers = usersResult.users || [];
    app.adminLoaded = true;
    renderPermissionGroupTable();
    populatePermissionUserDepartmentFilter();
    renderPermissionUsers();
  } catch (error) {
    $("permissionGroupTableBody").innerHTML =
      '<tr><td colspan="6" class="permission-table-empty"></td></tr>';
    $("permissionGroupTableBody").querySelector("td").textContent =
      `Không tải được phân quyền: ${error.message}`;
    $("permissionUserList").innerHTML =
      '<tr><td colspan="7" class="permission-table-empty"></td></tr>';
    $("permissionUserList").querySelector("td").textContent =
      `Không tải được người dùng: ${error.message}`;
    $("permissionUserResultCount").textContent = "Không có dữ liệu";
    toast(`Không tải được trang quản trị: ${error.message}`);
  }
}

const LOGIN_ACCOUNT_KEY = "mshai-remembered-username";

function clearLoginMessage() {
  $("loginFormMessage").classList.add("hidden");
  $("loginFormMessage").textContent = "";
}

function setLoginPasswordVisible(visible) {
  $("loginPassword").type = visible ? "text" : "password";
  const toggle = $("loginTogglePassword");
  toggle.setAttribute("aria-pressed", String(visible));
  toggle.setAttribute("aria-label", visible ? "Ẩn mật khẩu" : "Hiện mật khẩu");
  toggle.title = visible ? "Ẩn mật khẩu" : "Hiện mật khẩu";
  toggle
    .querySelector("use")
    .setAttribute("href", visible ? "#i-eye-off" : "#i-eye");
}

function setLoginMessage(message, type = "error") {
  const element = $("loginFormMessage");
  element.textContent = message;
  element.dataset.type = type;
  element.classList.toggle("hidden", !message);
}

function setAuthBusy(busy) {
  app.authBusy = busy;
  const button = $("loginSubmitButton");
  const fields = [
    $("loginUsername"),
    $("loginPassword"),
    $("loginRemember"),
    $("loginTogglePassword"),
  ];
  fields.forEach((field) => {
    field.disabled = busy;
  });
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
  button.querySelector("span").textContent = busy
    ? "Đang đăng nhập..."
    : "Đăng nhập";
}

function accountInitials(user) {
  const value = (user?.full_name || user?.username || "MH").trim();
  const parts = value.split(/\s+/).filter(Boolean);
  return parts
    .slice(-2)
    .map((part) => part[0])
    .join("")
    .toLocaleUpperCase("vi-VN");
}

function accountRoleLabel(role) {
  return (
    {
      admin: "Quản trị viên",
      manager: "Quản lý",
      employee: "Nhân viên",
    }[role] || "Tài khoản nội bộ"
  );
}

function closeAccountMenu({ restoreFocus = false } = {}) {
  const menu = $("accountMenu");
  if (menu.classList.contains("hidden")) return;
  menu.classList.add("hidden");
  $("loginButton").setAttribute("aria-expanded", "false");
  if (restoreFocus) $("loginButton").focus();
}

function toggleAccountMenu() {
  const menu = $("accountMenu");
  const shouldOpen = menu.classList.contains("hidden");
  if (!shouldOpen) {
    closeAccountMenu();
    return;
  }
  menu.classList.remove("hidden");
  $("loginButton").setAttribute("aria-expanded", "true");
  requestAnimationFrame(() => $("logoutButton").focus());
}

function syncAuthenticatedUser(user) {
  app.currentUser = user || null;
  const authenticated = Boolean(app.currentUser);
  const isAdmin = app.currentUser?.role === "admin";
  const shell = document.querySelector(".app-shell");
  shell.inert = !authenticated;
  document.body.classList.remove("auth-pending");
  document.body.classList.toggle("auth-required", !authenticated);
  $("adminButton").classList.toggle("hidden", !isAdmin);
  if (!isAdmin) {
    if (app.drawer === "admin") closeDrawer();
    app.adminGroups = [];
    app.adminUsers = [];
    app.adminLoaded = false;
  }

  const loginButton = $("loginButton");
  const label = loginButton.querySelector(".account-button-label");
  const chevron = loginButton.querySelector(".account-button-chevron");
  if (authenticated) {
    label.textContent = app.currentUser.full_name || app.currentUser.username;
    loginButton.title = "Mở menu tài khoản";
    loginButton.setAttribute("aria-label", loginButton.title);
    loginButton.setAttribute("aria-haspopup", "menu");
    loginButton.setAttribute("aria-controls", "accountMenu");
    loginButton.dataset.authenticated = "true";
    chevron.classList.remove("hidden");
    $("accountAvatar").textContent = accountInitials(app.currentUser);
    $("accountFullName").textContent = label.textContent;
    $("accountMeta").textContent = [
      accountRoleLabel(app.currentUser.role),
      app.currentUser.department || `@${app.currentUser.username}`,
    ].join(" · ");
  } else {
    closeAccountMenu();
    label.textContent = "Đăng nhập";
    loginButton.title = "Đăng nhập tài khoản nội bộ";
    loginButton.setAttribute("aria-label", loginButton.title);
    loginButton.setAttribute("aria-haspopup", "dialog");
    loginButton.setAttribute("aria-controls", "loginDialog");
    loginButton.setAttribute("aria-expanded", "false");
    delete loginButton.dataset.authenticated;
    chevron.classList.add("hidden");
    app.documents = [];
    app.documentsLoaded = false;
    app.aiProviders = [];
    app.defaultAiProvider = "";
    app.chats = [createChat()];
    app.currentId = app.chats[0].id;
    renderHistory();
    renderMessages();
  }
}

function openLoginDialog({ required = !app.currentUser } = {}) {
  closeDrawer();
  const dialog = $("loginDialog");
  if (dialog.open) return;
  dialog.dataset.required = String(required);
  clearLoginMessage();
  setAuthBusy(false);
  setLoginPasswordVisible(false);
  const savedUsername = localStorage.getItem(LOGIN_ACCOUNT_KEY) || "";
  $("loginRemember").checked = Boolean(savedUsername);
  $("loginUsername").value = savedUsername;
  $("loginPassword").value = "";
  dialog.showModal();
  $(savedUsername ? "loginPassword" : "loginUsername").focus();
}

async function finishAuthentication(user) {
  syncAuthenticatedUser(user);
  await loadUserChats();
  $("loginDialog").close();
  await Promise.all([loadTaxonomy(), loadAiProviders()]);
  $("messageInput").focus();
}

async function restoreAuthentication() {
  try {
    const result = await getCurrentUser();
    await finishAuthentication(result.user);
  } catch (error) {
    syncAuthenticatedUser(null);
    openLoginDialog({ required: true });
  }
}

async function submitLogin() {
  const username = $("loginUsername").value.trim();
  const password = $("loginPassword").value;
  if (!username) {
    $("loginUsername").focus();
    return;
  }
  if (!password) {
    $("loginPassword").focus();
    return;
  }

  setAuthBusy(true);
  clearLoginMessage();
  try {
    const result = await login(username, password);
    if ($("loginRemember").checked) {
      localStorage.setItem(LOGIN_ACCOUNT_KEY, username);
    } else {
      localStorage.removeItem(LOGIN_ACCOUNT_KEY);
    }
    await finishAuthentication(result.user);
    toast(`Xin chào ${result.user.full_name || result.user.username}`);
  } catch (error) {
    setLoginMessage(error.message || "Không thể đăng nhập.");
    $("loginPassword").select();
  } finally {
    setAuthBusy(false);
  }
}

async function signOut() {
  closeAccountMenu();
  const button = $("logoutButton");
  button.disabled = true;
  try {
    await logout();
  } catch (error) {
    if (error.status !== 401) {
      toast(`Không thể đăng xuất: ${error.message}`);
      return;
    }
  } finally {
    button.disabled = false;
  }
  syncAuthenticatedUser(null);
  openLoginDialog({ required: true });
}

function bindLoginEvents() {
  const dialog = $("loginDialog");
  $("loginButton").addEventListener("click", () => {
    if (app.currentUser) toggleAccountMenu();
    else openLoginDialog({ required: true });
  });
  $("logoutButton").addEventListener("click", signOut);
  document.addEventListener("click", (event) => {
    if (!$("accountControl").contains(event.target)) closeAccountMenu();
  });
  $("accountMenu").addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeAccountMenu({ restoreFocus: true });
    }
  });
  $("loginCloseButton").addEventListener("click", () => {
    if (app.currentUser) dialog.close();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && app.currentUser) dialog.close();
  });
  dialog.addEventListener("cancel", (event) => {
    if (!app.currentUser) event.preventDefault();
  });
  dialog.addEventListener("close", () => {
    $("loginPassword").value = "";
    setLoginPasswordVisible(false);
    clearLoginMessage();
  });
  $("loginTogglePassword").addEventListener("click", () => {
    const password = $("loginPassword");
    const start = password.selectionStart;
    const end = password.selectionEnd;
    setLoginPasswordVisible(password.type === "password");
    password.focus();
    if (start != null && end != null) password.setSelectionRange(start, end);
  });
  for (const id of ["loginUsername", "loginPassword"]) {
    $(id).addEventListener("input", clearLoginMessage);
  }
  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitLogin();
  });
  window.addEventListener("mshai:auth-required", () => {
    if (!app.currentUser && $("loginDialog").open) return;
    syncAuthenticatedUser(null);
    openLoginDialog({ required: true });
    setLoginMessage("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  });
}

function bindEvents() {
  bindLoginEvents();
  $("composerForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitComposer();
  });
  $("productImageButton").addEventListener("click", () =>
    $("productImageInput").click(),
  );
  $("productImageInput").addEventListener("change", (event) =>
    selectProductImage(event.target.files?.[0]),
  );
  $("removeProductImageButton").addEventListener("click", () => {
    clearProductImage();
    syncDataSource();
    $("messageInput").focus();
  });
  $("messageInput").addEventListener("input", resizeComposer);
  $("conversationScroll").addEventListener("scroll", updateScrollDownButton, {
    passive: true,
  });
  $("scrollDownButton").addEventListener("click", scrollConversationToBottom);
  $("messageInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("composerForm").requestSubmit();
    }
  });
  $("stopButton").addEventListener("click", stopGeneration);
  $("newButton").addEventListener("click", startNewChat);
  $("drawerNew").addEventListener("click", startNewChat);
  $("brandLink").addEventListener("click", (event) => {
    event.preventDefault();
    startNewChat();
  });
  $("historyButton").addEventListener("click", () => openDrawer("history"));
  $("adminButton").addEventListener("click", () => openDrawer("admin"));
  document.querySelectorAll("[data-admin-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      setAdminPanel(button.dataset.adminPanel);
    });
  });
  if (DEBUG_MODE) {
    $("documentsButton").addEventListener("click", () =>
      openDrawer("documents"),
    );
  }
  $("settingsButton").addEventListener("click", () => openDrawer("settings"));
  $("overlay").addEventListener("click", closeDrawer);
  document
    .querySelectorAll("[data-close]")
    .forEach((button) => button.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      ($("permissionGroupDialog").open ||
        $("permissionUserDialog").open ||
        $("createPermissionUserDialog").open)
    ) {
      return;
    }
    if (event.key === "Escape" && app.drawer) closeDrawer();
    if (event.key === "Escape") setScopeExpanded(false);
  });
  document.querySelectorAll("[data-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      submitMessage(button.dataset.suggestion);
    });
  });
  $("clearHistory").addEventListener("click", async () => {
    if (!window.confirm("Xóa toàn bộ lịch sử trò chuyện của tài khoản này?"))
      return;
    try {
      await clearConversations();
    } catch (error) {
      toast(error.message || "Không thể xóa lịch sử trò chuyện.");
      return;
    }
    app.chats = [createChat()];
    app.currentId = app.chats[0].id;
    storeChats();
    renderHistory();
    renderMessages();
    toast("Đã xóa toàn bộ lịch sử trò chuyện.");
  });

  $("scopeToggle").addEventListener("click", () => {
    const expanded = $("scopeToggle").getAttribute("aria-expanded") === "true";
    setScopeExpanded(!expanded);
  });
  document.addEventListener("click", (event) => {
    if (!$("scopePanel").contains(event.target)) setScopeExpanded(false);
  });
  $("chatDocumentType").addEventListener("change", () => {
    fillSelect(
      $("chatDocumentGroup"),
      groupsForType($("chatDocumentType").value),
      "Tất cả nhóm",
    );
    updateScopeSummary();
  });
  $("chatDocumentGroup").addEventListener("change", updateScopeSummary);
  $("documentTypeFilter").addEventListener("change", () => {
    fillSelect(
      $("documentGroupFilter"),
      groupsForType($("documentTypeFilter").value),
      "Tất cả nhóm",
    );
    renderDocuments();
  });
  $("documentGroupFilter").addEventListener("change", renderDocuments);
  $("documentSearch").addEventListener("input", renderDocuments);
  $("documentDialogClose").addEventListener("click", () =>
    $("documentDialog").close(),
  );

  $("permissionGroupSearch").addEventListener(
    "input",
    renderPermissionGroupTable,
  );
  $("permissionUserSearch").addEventListener("input", renderPermissionUsers);
  $("permissionDepartmentFilter").addEventListener(
    "change",
    renderPermissionUsers,
  );
  $("permissionStatusFilter").addEventListener(
    "change",
    renderPermissionUsers,
  );
  $("openCreatePermissionUserButton").addEventListener(
    "click",
    openCreatePermissionUserDialog,
  );
  $("openCreatePermissionGroupButton").addEventListener("click", () => {
    openPermissionGroupDialog();
  });
  $("closePermissionDialogButton").addEventListener(
    "click",
    closePermissionGroupDialog,
  );
  $("cancelPermissionDialogButton").addEventListener(
    "click",
    closePermissionGroupDialog,
  );
  $("deletePermissionGroupButton").addEventListener("click", async () => {
    await deleteEditingPermissionGroup();
  });
  $("permissionGroupDialog").addEventListener("click", (event) => {
    if (event.target === $("permissionGroupDialog")) {
      closePermissionGroupDialog();
    }
  });
  $("permissionGroupDescription").addEventListener("input", (event) => {
    $("permissionDescriptionCount").textContent = String(
      event.target.value.length,
    );
  });
  $("permissionGroupForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitPermissionGroupDialog();
  });
  $("assignUsersFromDialogButton").addEventListener("click", () => {
    closePermissionGroupDialog();
    setAdminPanel("users");
  });
  $("permissionUserGroupSearch").addEventListener(
    "input",
    renderPermissionUserGroupChoices,
  );
  $("permissionUserRole").addEventListener(
    "change",
    syncPermissionUserRoleControls,
  );
  $("permissionUserActive").addEventListener(
    "change",
    syncPermissionUserStatusControl,
  );
  $("togglePermissionPasswordResetButton").addEventListener("click", () => {
    const expanded =
      $("togglePermissionPasswordResetButton").getAttribute("aria-expanded") ===
      "true";
    setPermissionPasswordResetExpanded(!expanded);
    if (!expanded) $("permissionNewPassword").focus();
  });
  $("confirmPermissionPasswordResetButton").addEventListener(
    "click",
    submitPermissionPasswordReset,
  );
  for (const id of ["permissionNewPassword", "permissionConfirmPassword"]) {
    $(id).addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      submitPermissionPasswordReset();
    });
  }
  $("closePermissionUserDialogButton").addEventListener(
    "click",
    closePermissionUserDialog,
  );
  $("cancelPermissionUserDialogButton").addEventListener(
    "click",
    closePermissionUserDialog,
  );
  $("permissionUserDialog").addEventListener("click", (event) => {
    if (event.target === $("permissionUserDialog")) {
      closePermissionUserDialog();
    }
  });
  $("permissionUserDialog").addEventListener("close", () => {
    app.adminEditingUserId = "";
    setPermissionUserDialogBusy(false);
  });
  $("permissionUserForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitPermissionUserDialog();
  });
  $("closeCreatePermissionUserDialogButton").addEventListener(
    "click",
    closeCreatePermissionUserDialog,
  );
  $("cancelCreatePermissionUserButton").addEventListener(
    "click",
    closeCreatePermissionUserDialog,
  );
  $("createPermissionUserDialog").addEventListener("click", (event) => {
    if (event.target === $("createPermissionUserDialog")) {
      closeCreatePermissionUserDialog();
    }
  });
  $("createPermissionUserDialog").addEventListener("close", () => {
    setCreatePermissionUserBusy(false);
  });
  $("createPermissionUserForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitCreatePermissionUserDialog();
  });
  $("productGalleryClose").addEventListener("click", () =>
    $("productGalleryDialog").close(),
  );
  $("productGalleryDialog").addEventListener("click", (event) => {
    if (event.target === $("productGalleryDialog")) {
      $("productGalleryDialog").close();
    }
  });

  document.querySelectorAll(".theme-choice").forEach((button) =>
    button.addEventListener("click", () => {
      app.prefs.theme = button.dataset.theme;
      saveJSON(PREF_KEY, app.prefs);
      applyPrefs();
    }),
  );
  document.querySelectorAll(".accent-choice").forEach((button) =>
    button.addEventListener("click", () => {
      app.prefs.accent = button.dataset.accent;
      saveJSON(PREF_KEY, app.prefs);
      applyPrefs();
    }),
  );
  document.querySelectorAll(".font-choice").forEach((button) =>
    button.addEventListener("click", () => {
      app.prefs.font = button.dataset.font;
      saveJSON(PREF_KEY, app.prefs);
      applyPrefs();
    }),
  );
  $("aiProviderSelect").addEventListener("change", (event) => {
    app.prefs.aiProvider = event.target.value;
    saveJSON(PREF_KEY, app.prefs);
    syncAiProviderSelect();
  });
  $("resetSettings").addEventListener("click", () => {
    app.prefs = { ...defaults };
    syncAiProviderSelect();
    syncDataSource();
    saveJSON(PREF_KEY, app.prefs);
    applyPrefs();
    toast("Đã khôi phục giao diện mặc định");
  });
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", updateResolvedTheme);
  window.addEventListener("resize", updateComposerDockHeight);
  if ("ResizeObserver" in window) {
    app.composerResizeObserver = new ResizeObserver(updateComposerDockHeight);
    app.composerResizeObserver.observe(
      $("composerForm").closest(".composer-dock"),
    );
  }
}

async function checkHealth() {
  const indicator = document.querySelector(".demo-indicator");
  try {
    await getHealth();
    $("modeLabel").textContent = "RAG sẵn sàng";
    indicator.classList.remove("offline");
  } catch {
    $("modeLabel").textContent = "Mất kết nối";
    indicator.classList.add("offline");
  }
}

async function initialize() {
  app.chats = [createChat()];
  app.currentId = app.chats[0].id;
  app.prefs = { ...defaults, ...loadJSON(PREF_KEY, {}) };
  bindEvents();
  applyPrefs();
  syncDataSource();
  renderHistory();
  renderMessages();
  resizeComposer();
  updateComposerDockHeight();
  checkHealth();
  await restoreAuthentication();
}

initialize().catch((error) => {
  syncAuthenticatedUser(null);
  openLoginDialog({ required: true });
  setLoginMessage(error.message || "Không thể khởi tạo phiên đăng nhập.");
});
