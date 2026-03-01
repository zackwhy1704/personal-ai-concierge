const API_BASE = process.env.NEXT_PUBLIC_API || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('auth_token', token);
    }
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
    if (typeof window !== 'undefined') {
      localStorage.removeItem('auth_token');
    }
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = this.getToken();
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

    if (response.status === 401) {
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

  async createCheckout(plan: string) {
    return this.request<{ checkout_url: string; session_id: string }>('/api/billing/checkout', {
      method: 'POST',
      body: JSON.stringify({
        plan,
        success_url: `${window.location.origin}/dashboard/usage?payment=success`,
        cancel_url: `${window.location.origin}/dashboard/usage?payment=cancelled`,
      }),
    });
  }

  async cancelSubscription() {
    return this.request('/api/billing/cancel', { method: 'POST' });
  }

  async reactivateSubscription() {
    return this.request('/api/billing/reactivate', { method: 'POST' });
  }
}

export const api = new ApiClient();
