import {
  getDocument,
  getDocumentBySourceKey,
  getDocuments,
  getTaxonomy,
} from "./api.js";
import { $, errorMessage, escapeHtml, formatDate, icon } from "./ui.js";

let documents = [];
const groupsByCode = new Map();
const groupsById = new Map();
const docTypesById = new Map();
let taxonomy = [];
const OTHER_SECTION = "Khác";

function categoryName(document) {
  return (
    groupsByCode.get(document.category)?.name || document.category || "Khác"
  );
}

function sectionName(document) {
  return groupsByCode.get(document.category)?.docTypeName || OTHER_SECTION;
}

function categoryStyle(code) {
  const value = String(code || "").toLowerCase();
  if (/(product|san_pham)/.test(value)) return "product";
  if (/(policy|returns|warranty|shipping)/.test(value)) return "policy";
  if (/(guide|size|store)/.test(value)) return "guide";
  if (value.includes("faq")) return "faq";
  return "other";
}

function filteredDocuments() {
  const term = $("documentSearch").value.trim().toLocaleLowerCase("vi");
  const selectedTypeId = Number($("documentTypeFilter").value);
  const selectedGroupId = Number($("documentGroupFilter").value);
  const result = documents.filter((document) => {
    const group = groupsByCode.get(document.category);
    const documentTypeId = Number(document.doc_type_id || group?.doc_type_id);
    const documentGroupId = Number(document.group_id || group?.id);
    if (selectedTypeId && documentTypeId !== selectedTypeId) return false;
    if (selectedGroupId && documentGroupId !== selectedGroupId) return false;
    if (!term) return true;
    return `${document.title} ${document.description} ${categoryName(document)} ${sectionName(document)}`
      .toLocaleLowerCase("vi")
      .includes(term);
  });
  return result.sort((a, b) =>
    String(b.updated_at || "").localeCompare(a.updated_at || ""),
  );
}

function docRow(document) {
  return `
    <article class="doc-row" data-document-id="${escapeHtml(document.id)}" data-type="${categoryStyle(document.category)}" tabindex="0">
      <div class="doc-icon">${icon("file")}</div>
      <div class="doc-main">
        <div class="doc-title">${escapeHtml(document.title)}</div>
        <div class="doc-desc">${escapeHtml(document.description || "Chưa có mô tả.")}</div>
      </div>
      <div class="doc-meta">
        <span class="tag primary">${escapeHtml(categoryName(document))}</span>
        <span class="doc-date">${icon("cal")}${formatDate(document.updated_at)}</span>
      </div>
      <span class="doc-chevron">${icon("right")}</span>
    </article>`;
}

function renderDocuments() {
  const filtered = filteredDocuments();
  const container = $("documentSections");
  if (!filtered.length) {
    container.innerHTML = `<div class="empty"><strong>Không tìm thấy tài liệu</strong>Thử đổi từ khóa tìm kiếm.</div>`;
    return;
  }

  const order = [...docTypesById.values()].map((docType) => docType.name);
  const buckets = new Map();
  for (const document of filtered) {
    const name = sectionName(document);
    if (!buckets.has(name)) buckets.set(name, []);
    buckets.get(name).push(document);
  }
  const names = [...buckets.keys()].sort((a, b) => {
    const rank = (name) =>
      order.includes(name) ? order.indexOf(name) : order.length;
    return rank(a) - rank(b);
  });

  container.innerHTML = names
    .map(
      (name) => `
        <section class="doc-section">
          <div class="doc-section-head">
            <h2>${escapeHtml(name)}</h2>
            <span class="doc-section-count">${buckets.get(name).length} tài liệu</span>
          </div>
          <div class="doc-list">${buckets.get(name).map(docRow).join("")}</div>
        </section>`,
    )
    .join("");
}

function showDocumentDialog(title) {
  $("documentDialogTitle").textContent = title || "Tài liệu";
  $("documentDialogMeta").textContent = "";
  $("documentDialogContent").textContent = "";
  $("documentDialogState").textContent = "Đang tải nội dung…";
  const dialog = $("documentDialog");
  if (!dialog.open) dialog.showModal();
}

function renderDocumentDialog(document) {
  $("documentDialogTitle").textContent = document.title;
  $("documentDialogMeta").textContent = [
    categoryName(document),
    document.file_name,
    formatDate(document.updated_at),
  ]
    .filter(Boolean)
    .join(" · ");
  $("documentDialogState").textContent = document.content
    ? ""
    : "Tài liệu chưa có nội dung văn bản.";
  $("documentDialogContent").textContent = document.content || "";
}

async function openWith(loader, title) {
  showDocumentDialog(title);
  try {
    renderDocumentDialog(await loader());
  } catch (error) {
    $("documentDialogState").textContent = errorMessage(error);
  }
}

export function openDocumentBySourceKey(sourceKey, title = "Nguồn tài liệu") {
  return openWith(() => getDocumentBySourceKey(sourceKey), title);
}

export async function loadTaxonomy() {
  const data = await getTaxonomy();
  taxonomy = data.doc_types || [];
  groupsByCode.clear();
  groupsById.clear();
  docTypesById.clear();
  const typeSelect = $("chatDocumentType");
  const documentTypeSelect = $("documentTypeFilter");
  typeSelect.replaceChildren(new Option("Tất cả loại", ""));
  documentTypeSelect.replaceChildren(new Option("Tất cả loại", ""));
  for (const docType of taxonomy) {
    docTypesById.set(Number(docType.id), docType);
    for (const group of docType.groups || []) {
      const enrichedGroup = { ...group, docTypeName: docType.name };
      groupsByCode.set(group.code, enrichedGroup);
      groupsById.set(Number(group.id), enrichedGroup);
    }
    if (docType.is_active) {
      typeSelect.append(new Option(docType.name, String(docType.id)));
      documentTypeSelect.append(new Option(docType.name, String(docType.id)));
    }
  }
  updateChatGroupOptions();
  updateDocumentGroupOptions();
  if (documents.length) renderDocuments();
}

function updateDocumentGroupOptions() {
  const selectedTypeId = Number($("documentTypeFilter").value);
  const groupSelect = $("documentGroupFilter");
  groupSelect.replaceChildren(new Option("Tất cả nhóm", ""));
  const availableTypes = selectedTypeId
    ? taxonomy.filter((item) => Number(item.id) === selectedTypeId)
    : taxonomy;
  for (const docType of availableTypes) {
    if (!docType.is_active) continue;
    for (const group of docType.groups || []) {
      if (!group.is_active) continue;
      const label = selectedTypeId
        ? group.name
        : `${docType.name} › ${group.name}`;
      groupSelect.append(new Option(label, String(group.id)));
    }
  }
}

export function updateChatGroupOptions() {
  const selectedTypeId = Number($("chatDocumentType").value);
  const groupSelect = $("chatDocumentGroup");
  groupSelect.replaceChildren(new Option("Tất cả nhóm", ""));
  const availableTypes = selectedTypeId
    ? taxonomy.filter((item) => Number(item.id) === selectedTypeId)
    : taxonomy;
  for (const docType of availableTypes) {
    if (!docType.is_active) continue;
    for (const group of docType.groups || []) {
      if (!group.is_active) continue;
      const label = selectedTypeId
        ? group.name
        : `${docType.name} › ${group.name}`;
      groupSelect.append(new Option(label, String(group.id)));
    }
  }
  updateChatScopeSummary();
}

export function updateChatScopeSummary() {
  const typeId = Number($("chatDocumentType").value);
  const groupId = Number($("chatDocumentGroup").value);
  const docType = docTypesById.get(typeId);
  const group = groupsById.get(groupId);
  let label = "Tất cả tài liệu đang sử dụng";
  if (group) label = `${group.docTypeName} › ${group.name}`;
  else if (docType) label = `${docType.name} › Tất cả nhóm`;
  $("chatScopeSummary").textContent = label;
  $("chatScopeSummary").title = label;
}

export async function loadDocuments() {
  $("documentSections").innerHTML =
    `<div class="empty">Đang tải tài liệu…</div>`;
  try {
    const data = await getDocuments();
    documents = data.documents || [];
    renderDocuments();
  } catch (error) {
    $("documentSections").innerHTML =
      `<div class="empty"><strong>Không tải được tài liệu</strong>${escapeHtml(errorMessage(error))}</div>`;
  }
}

export function initializeDocumentsUI() {
  $("documentSearch").addEventListener("input", renderDocuments);
  $("documentTypeFilter").addEventListener("change", () => {
    updateDocumentGroupOptions();
    renderDocuments();
  });
  $("documentGroupFilter").addEventListener("change", renderDocuments);
  const open = (card) =>
    openWith(() => getDocument(card.dataset.documentId), "Tài liệu");
  $("documentSections").addEventListener("click", (event) => {
    const card = event.target.closest(".doc-row");
    if (card) open(card);
  });
  $("documentSections").addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    const card = event.target.closest(".doc-row");
    if (!card) return;
    event.preventDefault();
    open(card);
  });
  $("documentDialogClose").addEventListener("click", () =>
    $("documentDialog").close(),
  );
  $("documentDialog").addEventListener("click", (event) => {
    if (event.target === $("documentDialog")) $("documentDialog").close();
  });
}
