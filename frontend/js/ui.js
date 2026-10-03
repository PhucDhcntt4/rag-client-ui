export const $ = (id) => document.getElementById(id);

export const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );

const decodeNumericEntities = (value) =>
  String(value ?? "").replace(
    /&#(?:x([0-9a-f]+)|(\d+));/gi,
    (entity, hexadecimal, decimal) => {
      const codePoint = Number.parseInt(
        hexadecimal || decimal,
        hexadecimal ? 16 : 10,
      );
      if (
        !Number.isInteger(codePoint) ||
        codePoint < 0 ||
        codePoint > 0x10ffff ||
        (codePoint >= 0xd800 && codePoint <= 0xdfff)
      ) {
        return entity;
      }
      return String.fromCodePoint(codePoint);
    },
  );

const normalizeMarkdown = (value) =>
  decodeNumericEntities(value)
    .replaceAll("â€¢", "•")
    .replace(/^(\s*)\*\*•\*\*\s*/gm, "$1- ")
    .replace(/^(\s*)\*\*•\s*/gm, "$1- **")
    .replace(/^(\s*)•\s*/gm, "$1- ");

const renderInlineMarkdown = (value) => {
  const codeSpans = [];
  let text = escapeHtml(value).replace(/`([^`\n]+)`/g, (_match, code) => {
    const token = `@@CODE${codeSpans.length}@@`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });

  text = text
    .replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    )
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");

  return text.replace(/@@CODE(\d+)@@/g, (_match, index) => codeSpans[Number(index)]);
};

export function renderMarkdown(value) {
  const lines = normalizeMarkdown(value).replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!listItems.length) return;
    html.push(`<div class="md-list">${listItems.join("")}</div>`);
    listItems = [];
  };

  const tableCells = (line) => {
    let normalized = line.trim();
    if (normalized.startsWith("|")) normalized = normalized.slice(1);
    if (normalized.endsWith("|")) normalized = normalized.slice(0, -1);
    return normalized.split("|").map((cell) => cell.trim());
  };

  const isTableDivider = (line) => {
    const cells = tableCells(line);
    return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    if (
      line.includes("|") &&
      index + 1 < lines.length &&
      isTableDivider(lines[index + 1])
    ) {
      flushParagraph();
      flushList();
      const headers = tableCells(line);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      index -= 1;
      const headerHtml = headers
        .map((cell) => `<th scope="col">${renderInlineMarkdown(cell)}</th>`)
        .join("");
      const bodyHtml = rows
        .map(
          (row) =>
            `<tr>${headers
              .map((_header, cellIndex) => `<td>${renderInlineMarkdown(row[cellIndex] || "")}</td>`)
              .join("")}</tr>`,
        )
        .join("");
      html.push(
        `<div class="md-table-wrap"><table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`,
      );
      continue;
    }

    const heading = line.match(/^\s*(#{1,4})\s+(.+)$/);
    const listItem = line.match(/^(\s*)([-+*]|\d+[.)])\s+(.+)$/);
    const quote = line.match(/^\s*>\s?(.+)$/);

    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(heading[1].length + 2, 6);
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
    } else if (listItem) {
      flushParagraph();
      const depth = Math.min(Math.floor(listItem[1].replace(/\t/g, "  ").length / 2), 3);
      const ordered = /^\d/.test(listItem[2]);
      const marker = ordered ? escapeHtml(listItem[2].replace(/[.)]$/, ".")) : "&bull;";
      listItems.push(
        `<div class="md-list-item depth-${depth}"><span class="md-marker">${marker}</span><span>${renderInlineMarkdown(listItem[3])}</span></div>`,
      );
    } else if (quote) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
    } else if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      flushParagraph();
      flushList();
      html.push("<hr>");
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }

  flushParagraph();
  flushList();
  return html.join("");
}

export const icon = (name, className = "") =>
  `<svg class="ic ${className}"><use href="#i-${name}"/></svg>`;

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN").format(date);
}

export function errorMessage(error) {
  return error instanceof Error ? error.message : "Đã xảy ra lỗi không xác định.";
}
