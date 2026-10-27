import { API_BASE_URL } from "./config.js";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiRequest(path, options = {}) {
  const { skipAuthHandling = false, ...fetchOptions } = options;
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...fetchOptions,
      cache: "no-store",
      credentials: "include",
      headers: {
        ...fetchOptions.headers,
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
    if (response.status === 401 && !skipAuthHandling) {
      window.dispatchEvent(new CustomEvent("mshai:auth-required"));
    }
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
export const login = (username, password) =>
  apiRequest("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    skipAuthHandling: true,
  });
export const getCurrentUser = () =>
  apiRequest("/api/auth/me", { skipAuthHandling: true });
export const logout = () =>
  apiRequest("/api/auth/logout", {
    method: "POST",
    skipAuthHandling: true,
  });
export const getPermissionGroups = () =>
  apiRequest("/api/admin/permission-groups");
export const createPermissionGroup = (payload) =>
  apiRequest("/api/admin/permission-groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const updatePermissionGroup = (groupId, payload) =>
  apiRequest(`/api/admin/permission-groups/${encodeURIComponent(groupId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const deletePermissionGroup = (groupId) =>
  apiRequest(`/api/admin/permission-groups/${encodeURIComponent(groupId)}`, {
    method: "DELETE",
  });
export const updatePermissionScopes = (groupId, scopes) =>
  apiRequest(
    `/api/admin/permission-groups/${encodeURIComponent(groupId)}/scopes`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scopes }),
    },
  );
export const getAdminUsers = () => apiRequest("/api/admin/users");
export const createAdminUser = (payload) =>
  apiRequest("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const updateAdminUser = (userId, payload) =>
  apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
export const resetAdminUserPassword = (userId, newPassword) =>
  apiRequest(`/api/admin/users/${encodeURIComponent(userId)}/password`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_password: newPassword }),
  });
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

export const getConversations = (limit = 20) =>
  apiRequest(`/api/conversations?limit=${encodeURIComponent(limit)}`);

export const getConversation = (conversationId) =>
  apiRequest(`/api/conversations/${encodeURIComponent(conversationId)}`);

export const deleteConversation = (conversationId) =>
  apiRequest(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
  });

export const clearConversations = () =>
  apiRequest("/api/conversations", {
    method: "DELETE",
  });

export const saveConversationMessage = (conversationId, payload) =>
  apiRequest(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
