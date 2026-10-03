import { API_BASE_URL } from "./config.js";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      cache: "no-store",
      headers: {
        ...options.headers,
      },
    });
  } catch {
    throw new ApiError("Không thể kết nối RAG Client Backend.");
  }

  let body = null;
  try {
    body = await response.json();
  } catch {}

  if (!response.ok) {
    const detail = Array.isArray(body?.detail)
      ? body.detail
          .map((item) => item.msg)
          .filter(Boolean)
          .join("; ")
      : body?.detail;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : `Yêu cầu thất bại (${response.status}).`,
      response.status,
    );
  }
  if (body === null) throw new ApiError("Backend trả dữ liệu không hợp lệ.");
  return body;
}

export const getHealth = () => apiRequest("/api/health");
export const getTaxonomy = () => apiRequest("/api/taxonomy");
export const getDocuments = () => apiRequest("/api/documents");
export const getDocument = (id) =>
  apiRequest(`/api/documents/${encodeURIComponent(id)}`);
export const getDocumentBySourceKey = (sourceKey) =>
  apiRequest(
    `/api/documents/by-source-key?source_key=${encodeURIComponent(sourceKey)}`,
  );
export const sendChat = (payload) =>
  apiRequest("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
