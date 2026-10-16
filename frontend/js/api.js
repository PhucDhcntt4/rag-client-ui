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
  } catch (error) {
    if (error?.name === "AbortError") throw error;
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
export const getAiProviders = () => apiRequest("/api/ai/providers");
export const getTaxonomy = () => apiRequest("/api/taxonomy");
export const getDocuments = () => apiRequest("/api/documents");
export const getDocument = (id) =>
  apiRequest(`/api/documents/${encodeURIComponent(id)}`);
export const getDocumentBySourceKey = (sourceKey) =>
  apiRequest(
    `/api/documents/by-source-key?source_key=${encodeURIComponent(sourceKey)}`,
  );
export const getProducts = ({
  query = "",
  productType = "",
  status = "ACTIVE",
  page = 1,
  limit = 20,
} = {}) => {
  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  });
  if (query) params.set("q", query);
  if (productType) params.set("product_type", productType);
  if (status) params.set("status", status);
  return apiRequest(`/api/products?${params.toString()}`);
};
export const getLatestProducts = ({
  productType = "",
  page = 1,
  limit = 10,
  dateFrom = "",
  dateTo = "",
} = {}) => {
  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  });
  if (productType) params.set("product_type", productType);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return apiRequest(`/api/products/latest?${params.toString()}`);
};
export const getLatestProductDetails = ({
  page = 1,
  limit,
  dateFrom = "",
  dateTo = "",
} = {}) => {
  const params = new URLSearchParams({ page: String(page) });
  if (limit) params.set("limit", String(limit));
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return apiRequest(`/api/products/latest/details?${params.toString()}`);
};
export const getProduct = (productCode) =>
  apiRequest(`/api/products/${encodeURIComponent(productCode)}`);
export const searchProductsByImage = (file, signal) => {
  const form = new FormData();
  form.append("file", file, file.name);
  return apiRequest("/api/products/image-search", {
    method: "POST",
    body: form,
    ...(signal ? { signal } : {}),
  });
};
export const sendChat = (payload, signal) =>
  apiRequest("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    ...(signal ? { signal } : {}),
  });
