import axios from 'axios';
import { getToken, clearToken } from './auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});

// ── Request interceptor: attach JWT on every call ────────────────────────────
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor: handle 401 globally ────────────────────────────────
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      clearToken();
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/auth')) {
        window.location.href = '/auth/login';
      }
    }
    return Promise.reject(error);
  }
);

// ── Auth API ─────────────────────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  company_id: string | null;
  company_name: string | null;
  created_at: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export const authLogin = async (email: string, password: string): Promise<LoginResponse> => {
  const res = await api.post<LoginResponse>('/auth/login', { email, password });
  return res.data;
};

export const authRegister = async (
  email: string,
  password: string,
  company_name: string,
): Promise<LoginResponse> => {
  const res = await api.post<LoginResponse>('/auth/register', { email, password, company_name });
  return res.data;
};

export const authMe = async (): Promise<AuthUser> => {
  const res = await api.get<AuthUser>('/auth/me');
  return res.data;
};

export const authLogout = async (): Promise<void> => {
  await api.post('/auth/logout').catch(() => {
    // Server logout is best-effort — JWT is stateless; client drops the token
  });
};

// ---- Tenders ----
export interface TenderListItem {
  id: string;
  platform: string;
  external_id: string;
  title: string;
  category: string | null;
  budget: number | null;
  currency: string;
  status: string;
  customer_name: string | null;
  published_at: string | null;
  deadline_at: string | null;
  first_seen_at: string | null;
  is_profitable: boolean | null;
  profit_margin: number | null;
  confidence_level: string | null;
  expected_profit: number | null;
}

export interface TenderListResponse {
  items: TenderListItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface TenderFilters {
  platform?: string;
  category?: string;
  is_profitable?: boolean;
  confidence_level?: string;
  min_budget?: number;
  max_budget?: number;
  search?: string;
  page?: number;
  per_page?: number;
}

export const fetchTenders = async (filters: TenderFilters = {}): Promise<TenderListResponse> => {
  const params = Object.fromEntries(
    Object.entries(filters).filter(([_, v]) => v !== undefined && v !== '')
  );
  const response = await api.get('/tenders', { params });
  return response.data;
};

// ---- Lots (lot-level list with profitability data) ----
export interface LotListItem {
  id: string;
  tender_id: string;
  platform: string;
  tender_external_id: string;   // procurement number
  lot_external_id: string;      // lot number
  title: string;
  category: string | null;
  budget: number | null;
  currency: string;
  quantity: number | null;
  unit: string | null;
  status: string;
  deadline_at: string | null;
  first_seen_at: string | null;
  is_profitable: boolean | null;
  profit_margin_percent: number | null;
  confidence_level: string | null;
  expected_profit: number | null;
  is_analyzed: boolean;
  notification_sent: boolean;
  product_name: string | null;
  characteristics: string | null;
  ai_summary_ru: string | null;
  spec_clarity: string | null;
  profit_label: 'high' | 'medium' | 'low' | 'loss' | 'unknown';
  customer_name: string | null;
  customer_region: string | null;
  tender_title: string;
  accuracy_pct: number | null;
  is_suspicious: boolean;
  opportunity_score: number | null;
  days_until_deadline: number | null;
}

export interface LotListResponse {
  items: LotListItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface LotFilters {
  platform?: string;
  category?: string;
  is_profitable?: boolean;
  confidence_level?: string;
  min_budget?: number;
  max_budget?: number;
  search?: string;
  min_accuracy?: number;
  only_analyzed?: boolean;
  new_today?: boolean;
  sort_by?: 'newest' | 'deadline' | 'budget' | 'margin' | 'profit';
  page?: number;
  per_page?: number;
}

export interface TopLotItem {
  id: string;
  tender_id: string;
  platform: string;
  tender_external_id: string;
  title: string;
  category: string;
  budget: number | null;
  profit_margin_percent: number | null;
  expected_profit: number | null;
  confidence_level: string | null;
  opportunity_score: number;
  days_until_deadline: number | null;
  deadline_at: string | null;
  first_seen_at: string | null;
  customer_name: string | null;
  customer_region: string | null;
}

export const fetchTopLots = async (limit = 8, minMargin = 10): Promise<{ items: TopLotItem[]; total: number }> => {
  const response = await api.get('/lots/top', { params: { limit, min_margin: minMargin } });
  return response.data;
};

export const fetchLots = async (filters: LotFilters = {}): Promise<LotListResponse> => {
  const params = Object.fromEntries(
    Object.entries(filters).filter(([_, v]) => v !== undefined && v !== '')
  );
  const response = await api.get('/lots', { params });
  return response.data;
};

export const fetchTenderDetail = async (id: string) => {
  const response = await api.get(`/tenders/${id}`);
  return response.data;
};

export const fetchLotDetail = async (id: string) => {
  const response = await api.get(`/lots/${id}`);
  return response.data;
};

export const downloadLotDocument = async (lotId: string, docIndex: number) => {
  const response = await api.get(`/lots/${lotId}/download/${docIndex}`, {
    responseType: 'blob',
  });

  const disposition = response.headers['content-disposition'] || response.headers['Content-Disposition'] || '';
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/);
  const filename = filenameMatch ? filenameMatch[1].trim() : `lot-${lotId}-doc-${docIndex}.pdf`;

  return { blob: response.data as Blob, filename };
};

export const openLotDocument = async (lotId: string, docIndex: number) => {
  const response = await api.get(`/lots/${lotId}/view/${docIndex}`, {
    responseType: 'blob',
  });

  const disposition = response.headers['content-disposition'] || response.headers['Content-Disposition'] || '';
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/);
  const filename = filenameMatch ? filenameMatch[1].trim() : `lot-${lotId}-doc-${docIndex}.pdf`;

  return { blob: response.data as Blob, filename };
};

export const recordAction = async (tenderId: string, action: string, data?: any) => {
  const response = await api.post(`/tenders/${tenderId}/action`, {
    tender_id: tenderId,
    action,
    ...data,
  });
  return response.data;
};

export const recordLotAction = async (lotId: string, action: string) => {
  const response = await api.post(`/lots/${lotId}/action`, null, { params: { action } });
  return response.data;
};

export const reanalyzeLot = async (lotId: string) => {
  const response = await api.post(`/lots/${lotId}/reanalyze`);
  return response.data;
};

export const exportLotsExcel = async (filters: Omit<LotFilters, 'page' | 'per_page'> = {}): Promise<Blob> => {
  const params = Object.fromEntries(
    Object.entries(filters).filter(([_, v]) => v !== undefined && v !== '')
  );
  const response = await api.get('/lots/export', {
    params,
    responseType: 'blob',
  });
  return response.data;
};

export const reanalyzeLotFull = async (lotId: string) => {
  const response = await api.post(`/lots/${lotId}/reanalyze-full`);
  return response.data;
};

export const getBidUrl = (tenderId: string, companyName: string, companyBin: string) =>
  `${API_URL}/api/v1/tenders/${tenderId}/bid?company_name=${encodeURIComponent(companyName)}&company_bin=${encodeURIComponent(companyBin)}`;

export const getLotBidUrl = (lotId: string, companyName: string, companyBin: string) =>
  `${API_URL}/api/v1/lots/${lotId}/bid?company_name=${encodeURIComponent(companyName)}&company_bin=${encodeURIComponent(companyBin)}`;

// ---- Analytics ----
export const fetchDashboardSummary = async () => {
  const response = await api.get('/analytics/summary');
  return response.data;
};

export const fetchTrends = async (days = 30) => {
  const response = await api.get('/analytics/trends', { params: { days } });
  return response.data;
};

export const fetchTopCategories = async () => {
  const response = await api.get('/analytics/top-categories');
  return response.data;
};

export const fetchScanHistory = async (limit = 20) => {
  const response = await api.get('/analytics/scan-history', { params: { limit } });
  return response.data;
};

export const fetchMarginDistribution = async () => {
  const response = await api.get('/analytics/margin-distribution');
  return response.data;
};

export const fetchPlatformBreakdown = async () => {
  const response = await api.get('/analytics/platform-breakdown');
  return response.data;
};

export const fetchCategoryProfitability = async () => {
  const response = await api.get('/analytics/category-profitability');
  return response.data;
};

export const fetchConfidenceBreakdown = async () => {
  const response = await api.get('/analytics/confidence-breakdown');
  return response.data;
};

// ---- Scan ----
export const triggerScan = async () => {
  const response = await api.post('/scan/trigger');
  return response.data;
};

export const getScanStatus = async () => {
  const response = await api.get('/scan/status');
  return response.data;
};

export const triggerRecalculate = async () => {
  const response = await api.post('/scan/recalculate-profitability');
  return response.data;
};

export const getRecalculateStatus = async () => {
  const response = await api.get('/scan/recalculate-status');
  return response.data;
};

export const getAnalyzeEstimate = async (mode: string) => {
  const response = await api.get('/scan/analyze-estimate', { params: { mode } });
  return response.data;
};

export const triggerAnalyzeLots = async (mode: string) => {
  const response = await api.post('/scan/analyze-lots', null, { params: { mode } });
  return response.data;
};

export const getAnalyzeStatus = async () => {
  const response = await api.get('/scan/analyze-status');
  return response.data;
};

export const getAiCostLog = async () => {
  const response = await api.get('/scan/ai-cost-log');
  return response.data;
};

// ---- User Settings & Subscription ----

export interface FilterSettings {
  categories: string[];
  keywords: string[];
  exclude_keywords: string[];
  platforms: string[];
  min_budget: number | null;
  max_budget: number | null;
  min_margin: number | null;
  regions: string[];
}

export interface NotificationSettings {
  telegram: boolean;
  email: boolean;
  min_profit_for_notify: number;
}

export interface UserSettings {
  filters: FilterSettings;
  notifications: NotificationSettings;
  updated_at: string | null;
}

export interface SubscriptionInfo {
  plan: string;
  is_active: boolean;
  expires_at: string | null;
  days_left: number | null;
  trial_used?: boolean;
  limits: {
    lots_per_day: number;
    ai_details: boolean;
    bid_generator: boolean;
    export: boolean;
  };
  features: string[];
}

export const getUserSettings = async (): Promise<UserSettings> => {
  const response = await api.get('/users/me/settings');
  return response.data;
};

export const saveUserSettings = async (settings: Omit<UserSettings, 'updated_at'>): Promise<UserSettings> => {
  const response = await api.put('/users/me/settings', settings);
  return response.data;
};

export const getSubscription = async (): Promise<SubscriptionInfo> => {
  const response = await api.get('/users/me/subscription');
  return response.data;
};

export const activateTrial = async (): Promise<SubscriptionInfo> => {
  const response = await api.post('/users/me/subscription/trial', {});
  return response.data;
};

