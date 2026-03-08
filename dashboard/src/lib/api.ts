const API_BASE = process.env.NEXT_PUBLIC_API || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private token: string | null = null;
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private refreshPromise: Promise<void> | null = null;

  setToken(token: string) {
    this.token = token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('auth_token', token);
    }
    // Start refresh timer for JWT tokens (not API keys)
    this.scheduleTokenRefresh(token);
  }

  getToken(): string | null {
    if (this.token) return this.token;
    if (typeof window !== 'undefined') {
      this.token = localStorage.getItem('auth_token');
    }
    return this.token;
  }

  clearToken() {
    this.token = null;
    this.clearRefreshTimer();
    if (typeof window !== 'undefined') {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('managed_token');
      localStorage.removeItem('managed_tenant_id');
      localStorage.removeItem('managed_tenant_name');
    }
  }

  isAdmin(): boolean {
    const token = this.getToken();
    return !!token && token.startsWith('pac_admin_');
  }

  setManagedToken(jwt: string, tenantId: string, tenantName: string) {
    if (typeof window !== 'undefined') {
      localStorage.setItem('managed_token', jwt);
      localStorage.setItem('managed_tenant_id', tenantId);
      localStorage.setItem('managed_tenant_name', tenantName);
    }
    this.scheduleTokenRefresh(jwt, true);
  }

  getManagedToken(): string | null {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('managed_token');
    }
    return null;
  }

  getManagedTenantName(): string | null {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('managed_tenant_name');
    }
    return null;
  }

  getManagedTenantId(): string | null {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('managed_tenant_id');
    }
    return null;
  }

  clearManagedToken() {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('managed_token');
      localStorage.removeItem('managed_tenant_id');
      localStorage.removeItem('managed_tenant_name');
    }
  }

  // ── Token refresh logic ──────────────────────────────────

  private decodeJwtExpiry(token: string): number | null {
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return null;
      const payload = JSON.parse(atob(parts[1]));
      return payload.exp || null;
    } catch {
      return null;
    }
  }

  private clearRefreshTimer() {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
  }

  private scheduleTokenRefresh(token: string, isManaged = false) {
    // Only schedule for JWT tokens (not API keys starting with pac_)
    if (token.startsWith('pac_')) return;

    const exp = this.decodeJwtExpiry(token);
    if (!exp) return;

    const nowSec = Math.floor(Date.now() / 1000);
    const remainingSec = exp - nowSec;

    // Refresh 5 minutes before expiry, or immediately if <5 min left
    const refreshInMs = Math.max((remainingSec - 300) * 1000, 0);

    this.clearRefreshTimer();
    this.refreshTimer = setTimeout(() => {
      this.doRefresh(token, isManaged).catch(() => {
        // If refresh fails, user will get a 401 on next request and be redirected to login
      });
    }, refreshInMs);
  }

  private async doRefresh(token: string, isManaged: boolean): Promise<void> {
    // Prevent concurrent refreshes
    if (this.refreshPromise) return this.refreshPromise;

    this.refreshPromise = (async () => {
      try {
        const response = await fetch(`${API_BASE}/api/auth/refresh`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!response.ok) return;

        const data = await response.json();
        const newToken = data.token;

        if (isManaged) {
          if (typeof window !== 'undefined') {
            localStorage.setItem('managed_token', newToken);
          }
          this.scheduleTokenRefresh(newToken, true);
        } else {
          this.token = newToken;
          if (typeof window !== 'undefined') {
            localStorage.setItem('auth_token', newToken);
          }
          this.scheduleTokenRefresh(newToken, false);
        }
      } finally {
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  /**
   * Initialize refresh timers for any stored tokens on page load.
   * Call this once from the app's root layout or page.
   */
  initTokenRefresh() {
    if (typeof window === 'undefined') return;

    const authToken = localStorage.getItem('auth_token');
    if (authToken && !authToken.startsWith('pac_')) {
      this.scheduleTokenRefresh(authToken, false);
    }

    const managedToken = localStorage.getItem('managed_token');
    if (managedToken) {
      this.scheduleTokenRefresh(managedToken, true);
    }
  }

  // ── Request method ──────────────────────────────────────

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    // If admin is managing a tenant, use the managed JWT for tenant-scoped requests
    const managedToken = this.getManagedToken();
    const adminToken = this.getToken();

    // Admin-only endpoints always use the admin token
    const isAdminEndpoint = path === '/api/tenants' && (!options.method || options.method === 'GET')
      || (path.startsWith('/api/tenants/') && path.endsWith('/token'))
      || (path.startsWith('/api/tenants') && options.method === 'POST' && !path.includes('/me'));

    let token: string | null;
    if (isAdminEndpoint && this.isAdmin()) {
      token = adminToken;
    } else if (managedToken && this.isAdmin()) {
      token = managedToken;
    } else {
      token = adminToken;
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string> || {}),
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    // On 401, try refreshing the token once before giving up
    if (response.status === 401 && token && !token.startsWith('pac_')) {
      const isManaged = !!(managedToken && this.isAdmin() && !isAdminEndpoint);
      try {
        await this.doRefresh(token, isManaged);
        // Retry the request with the new token
        const newToken = isManaged ? this.getManagedToken() : this.getToken();
        if (newToken && newToken !== token) {
          headers['Authorization'] = `Bearer ${newToken}`;
          const retryResponse = await fetch(`${API_BASE}${path}`, { ...options, headers });
          if (retryResponse.ok) return retryResponse.json();
        }
      } catch {
        // Refresh failed, fall through to redirect
      }

      this.clearToken();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      throw new Error('Unauthorized');
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // Tenant
  async getMe() {
    return this.request('/api/tenants/me');
  }

  async updateMe(data: Record<string, unknown>) {
    return this.request('/api/tenants/me', { method: 'PATCH', body: JSON.stringify(data) });
  }

  // Admin - Tenant Management
  async listTenants() {
    return this.request<Array<Record<string, unknown>>>('/api/tenants');
  }

  async createTenant(data: Record<string, unknown>) {
    return this.request('/api/tenants', { method: 'POST', body: JSON.stringify(data) });
  }

  async updateTenant(id: string, data: Record<string, unknown>) {
    return this.request(`/api/tenants/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }

  async getTenantToken(id: string) {
    return this.request<{ jwt_token: string; tenant_id: string; tenant_name: string }>(
      `/api/tenants/${id}/token`, { method: 'POST' }
    );
  }

  // Guardrails
  async createGuardrailFromForm(data: Record<string, unknown>) {
    return this.request('/api/guardrails/from-form', { method: 'POST', body: JSON.stringify(data) });
  }

  async getActiveGuardrail() {
    return this.request('/api/guardrails/active');
  }

  async getGuardrailVersions() {
    return this.request<Array<Record<string, unknown>>>('/api/guardrails/versions');
  }

  // Usage
  async getMonthlyUsage(year?: number, month?: number) {
    const params = new URLSearchParams();
    if (year) params.set('year', String(year));
    if (month) params.set('month', String(month));
    return this.request(`/api/usage/monthly?${params}`);
  }

  // Intents
  async listIntents() {
    return this.request<Array<Record<string, unknown>>>('/api/intents');
  }

  async createIntent(data: Record<string, unknown>) {
    return this.request('/api/intents', { method: 'POST', body: JSON.stringify(data) });
  }

  async deleteIntent(id: string) {
    return this.request(`/api/intents/${id}`, { method: 'DELETE' });
  }

  async testIntent(message: string) {
    return this.request('/api/intents/test', { method: 'POST', body: JSON.stringify({ message }) });
  }

  // Knowledge
  async listDocuments() {
    return this.request<Array<Record<string, unknown>>>('/api/knowledge');
  }

  async uploadDocument(data: { title: string; content: string }) {
    return this.request('/api/knowledge', { method: 'POST', body: JSON.stringify(data) });
  }

  async deleteDocument(id: string) {
    return this.request(`/api/knowledge/${id}`, { method: 'DELETE' });
  }

  async searchKnowledge(query: string) {
    return this.request<Array<Record<string, unknown>>>('/api/knowledge/search', {
      method: 'POST', body: JSON.stringify({ query }),
    });
  }

  // Billing
  async getSubscriptionStatus() {
    return this.request('/api/billing/subscription');
  }

  async createCheckout(plan: string, promoCode?: string) {
    const payload: Record<string, string> = {
      plan,
      success_url: `${window.location.origin}/dashboard/usage?payment=success`,
      cancel_url: `${window.location.origin}/dashboard/usage?payment=cancelled`,
    };
    if (promoCode) payload.promo_code = promoCode;
    return this.request<{ checkout_url: string; session_id: string }>('/api/billing/checkout', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async cancelSubscription() {
    return this.request('/api/billing/cancel', { method: 'POST' });
  }

  async reactivateSubscription() {
    return this.request('/api/billing/reactivate', { method: 'POST' });
  }

  async getPricing(currency: string = 'MYR') {
    return this.request(`/api/billing/pricing?currency=${currency}`);
  }

  // Promo Codes
  async validatePromoCode(code: string) {
    return this.request<{ valid: boolean; code: string; trial_days: number; message: string }>(
      '/api/promo/validate', { method: 'POST', body: JSON.stringify({ code }) }
    );
  }

  async listPromoCodes() {
    return this.request<Array<Record<string, unknown>>>('/api/promo');
  }

  async createPromoCode(data: Record<string, unknown>) {
    return this.request('/api/promo', { method: 'POST', body: JSON.stringify(data) });
  }

  async deactivatePromoCode(id: string) {
    return this.request(`/api/promo/${id}/deactivate`, { method: 'PATCH' });
  }

  // Products
  async listProducts(category?: string) {
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    return this.request<Array<Record<string, unknown>>>(`/api/products?${params}`);
  }

  async createProduct(data: Record<string, unknown>) {
    return this.request('/api/products', { method: 'POST', body: JSON.stringify(data) });
  }

  async updateProduct(id: string, data: Record<string, unknown>) {
    return this.request(`/api/products/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }

  async deleteProduct(id: string) {
    return this.request(`/api/products/${id}`, { method: 'DELETE' });
  }

  async searchProducts(query: string) {
    return this.request<Record<string, unknown>>('/api/products/search', {
      method: 'POST', body: JSON.stringify({ query }),
    });
  }

  async importProducts(products: Array<Record<string, unknown>>) {
    return this.request('/api/products/import', {
      method: 'POST', body: JSON.stringify(products),
    });
  }

  // Upsell Strategies
  async listStrategies() {
    return this.request<Array<Record<string, unknown>>>('/api/upsell/strategies');
  }

  async createStrategy(data: Record<string, unknown>) {
    return this.request('/api/upsell/strategies', { method: 'POST', body: JSON.stringify(data) });
  }

  async updateStrategy(id: string, data: Record<string, unknown>) {
    return this.request(`/api/upsell/strategies/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }

  async deleteStrategy(id: string) {
    return this.request(`/api/upsell/strategies/${id}`, { method: 'DELETE' });
  }

  async toggleStrategy(id: string) {
    return this.request<{ status: string; is_active: boolean }>(
      `/api/upsell/strategies/${id}/toggle`, { method: 'POST' }
    );
  }

  async testStrategies(message: string) {
    return this.request<Record<string, unknown>>('/api/upsell/strategies/test', {
      method: 'POST', body: JSON.stringify({ message }),
    });
  }

  // Sales Analytics
  async getSalesDashboard(days?: number) {
    const params = new URLSearchParams();
    if (days) params.set('days', String(days));
    return this.request<Record<string, unknown>>(`/api/sales/dashboard?${params}`);
  }

  async getProductPerformance() {
    return this.request<Record<string, unknown>>('/api/sales/products/performance');
  }

  async getStrategyPerformance() {
    return this.request<Record<string, unknown>>('/api/sales/strategies/performance');
  }

  async analyzeLearning() {
    return this.request<Record<string, unknown>>('/api/sales/learning/analyze', { method: 'POST' });
  }

  async optimizeLearning() {
    return this.request<Record<string, unknown>>('/api/sales/learning/optimize', { method: 'POST' });
  }
}

export const api = new ApiClient();
