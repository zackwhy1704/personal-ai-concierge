'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export default function DashboardPage() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [hasManaged, setHasManaged] = useState(false)

  useEffect(() => {
    setIsAdmin(api.isAdmin())
    setHasManaged(!!api.getManagedToken())
  }, [])

  if (isAdmin && !hasManaged) {
    return <AdminDashboard />
  }
  return <TenantDashboard />
}

// ─── Tenant Dashboard (existing) ───────────────────────────────────────────

function TenantDashboard() {
  const [tenant, setTenant] = useState<Record<string, unknown> | null>(null)
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadData() {
      try {
        const [t, u] = await Promise.all([api.getMe(), api.getMonthlyUsage()])
        setTenant(t as Record<string, unknown>)
        setUsage(u as Record<string, unknown>)
      } catch (err) {
        console.error('Failed to load dashboard data:', err)
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [])

  if (loading) return <div className="text-gray-500">Loading...</div>

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Dashboard Overview</h1>

      {tenant && (
        <div className="mb-8 p-6 bg-white rounded-xl shadow-sm border">
          <h2 className="text-lg font-semibold text-gray-700 mb-3">Tenant Info</h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div><span className="text-gray-500">Name:</span> <span className="font-medium">{String(tenant.name)}</span></div>
            <div><span className="text-gray-500">Plan:</span> <span className="font-medium capitalize">{String(tenant.plan)}</span></div>
            <div><span className="text-gray-500">Status:</span> <span className="font-medium capitalize">{String(tenant.status)}</span></div>
            <div><span className="text-gray-500">WhatsApp:</span> <span className="font-medium">{tenant.whatsapp_phone_number_id ? 'Connected' : 'Not configured'}</span></div>
          </div>
        </div>
      )}

      {usage && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <StatCard label="Conversations" value={String(usage.total_conversations)} subtitle={`of ${usage.included_conversations} included`} />
          <StatCard label="Messages" value={String(usage.total_messages)} subtitle="this month" />
          <StatCard label="Remaining" value={String(usage.remaining_conversations)} subtitle="conversations" />
          <StatCard label="Overage Cost" value={`RM${usage.overage_cost}`} subtitle={`${usage.overage_conversations} extra conversations`} />
        </div>
      )}
    </div>
  )
}

// ─── Admin Dashboard ───────────────────────────────────────────────────────

function AdminDashboard() {
  const [tenants, setTenants] = useState<Array<Record<string, unknown>>>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    name: '',
    slug: '',
    plan: 'starter',
    whatsapp_phone_number_id: '',
    admin_phone_numbers: '',
  })

  useEffect(() => { loadTenants() }, [])

  async function loadTenants() {
    try {
      const data = await api.listTenants()
      setTenants(data)
    } catch (err) {
      console.error('Failed to load tenants:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      const payload: Record<string, unknown> = {
        name: form.name,
        slug: form.slug || form.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, ''),
        plan: form.plan,
      }
      if (form.whatsapp_phone_number_id) payload.whatsapp_phone_number_id = form.whatsapp_phone_number_id
      if (form.admin_phone_numbers) payload.admin_phone_numbers = form.admin_phone_numbers

      const result = await api.createTenant(payload) as Record<string, unknown>
      const tenant = result.tenant as Record<string, unknown>
      alert(`Tenant created!\n\nAPI Key: ${result.api_key}\nJWT Token: ${result.jwt_token}\n\nSave these - they won't be shown again.`)
      setShowCreate(false)
      setForm({ name: '', slug: '', plan: 'starter', whatsapp_phone_number_id: '', admin_phone_numbers: '' })
      // If tenant was created with the response having an id
      if (tenant?.id) {
        loadTenants()
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to create tenant')
    } finally {
      setCreating(false)
    }
  }

  async function handleManage(tenantId: string, tenantName: string) {
    try {
      const result = await api.getTenantToken(tenantId)
      api.setManagedToken(result.jwt_token, tenantId, tenantName)
      window.location.href = '/dashboard'
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to get tenant token')
    }
  }

  if (loading) return <div className="text-gray-500">Loading...</div>

  const planCounts: Record<string, number> = {}
  tenants.forEach(t => {
    const plan = String(t.plan)
    planCounts[plan] = (planCounts[plan] || 0) + 1
  })

  const activeTenants = tenants.filter(t => t.status === 'active').length

  return (
    <div className="max-w-5xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-800">All Tenants</h1>
        <button onClick={() => setShowCreate(!showCreate)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
          {showCreate ? 'Cancel' : '+ Create Tenant'}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Tenants" value={String(tenants.length)} subtitle="accounts" />
        <StatCard label="Active" value={String(activeTenants)} subtitle="tenants" />
        <StatCard label="Starter" value={String(planCounts.starter || 0)} subtitle="RM780/mo each" />
        <StatCard label="Professional" value={String(planCounts.professional || 0)} subtitle="RM2,800/mo each" />
      </div>

      {/* Create Form */}
      {showCreate && (
        <form onSubmit={handleCreate} className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <h3 className="font-semibold text-gray-700 mb-4">New Tenant</h3>
          <div className="grid grid-cols-2 gap-3">
            <input value={form.name}
              onChange={e => {
                const name = e.target.value
                setForm(p => ({
                  ...p,
                  name,
                  slug: name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, ''),
                }))
              }}
              placeholder="Business Name" className="px-3 py-2 border rounded-lg text-sm" required />
            <input value={form.slug}
              onChange={e => setForm(p => ({ ...p, slug: e.target.value }))}
              placeholder="slug (auto-generated)" className="px-3 py-2 border rounded-lg text-sm" />
            <select value={form.plan}
              onChange={e => setForm(p => ({ ...p, plan: e.target.value }))}
              className="px-3 py-2 border rounded-lg text-sm bg-white">
              <option value="starter">Starter (RM780/mo)</option>
              <option value="professional">Professional (RM2,800/mo)</option>
              <option value="enterprise">Enterprise (RM6,800/mo)</option>
            </select>
            <input value={form.whatsapp_phone_number_id}
              onChange={e => setForm(p => ({ ...p, whatsapp_phone_number_id: e.target.value }))}
              placeholder="WhatsApp Phone Number ID (optional)" className="px-3 py-2 border rounded-lg text-sm" />
            <input value={form.admin_phone_numbers}
              onChange={e => setForm(p => ({ ...p, admin_phone_numbers: e.target.value }))}
              placeholder="Admin phones: +65..., +60... (optional)"
              className="col-span-2 px-3 py-2 border rounded-lg text-sm" />
          </div>
          <button type="submit" disabled={creating}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
            {creating ? 'Creating...' : 'Create Tenant'}
          </button>
        </form>
      )}

      {/* Tenant List */}
      <div className="space-y-3">
        {tenants.map(tenant => (
          <div key={String(tenant.id)} className="p-4 bg-white rounded-xl shadow-sm border flex justify-between items-center">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h4 className="font-medium text-gray-800">{String(tenant.name)}</h4>
                <PlanBadge plan={String(tenant.plan)} />
                <StatusBadge status={String(tenant.status)} />
              </div>
              <p className="text-xs text-gray-400 mt-1">
                ID: {String(tenant.id).slice(0, 8)}... | Slug: {String(tenant.slug)} | Created: {new Date(String(tenant.created_at)).toLocaleDateString()}
              </p>
              {String(tenant.whatsapp_phone_number_id || '') && (
                <p className="text-xs text-green-600 mt-0.5">WhatsApp: {String(tenant.whatsapp_phone_number_id)}</p>
              )}
            </div>
            <button onClick={() => handleManage(String(tenant.id), String(tenant.name))}
              className="px-4 py-2 bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900 ml-4">
              Manage
            </button>
          </div>
        ))}
        {tenants.length === 0 && (
          <p className="text-gray-500 text-center py-8">No tenants yet. Create one to get started.</p>
        )}
      </div>
    </div>
  )
}

// ─── Shared Components ─────────────────────────────────────────────────────

function StatCard({ label, value, subtitle }: { label: string; value: string; subtitle: string }) {
  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-gray-800 mt-1">{value}</p>
      <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
    </div>
  )
}

function PlanBadge({ plan }: { plan: string }) {
  const colors: Record<string, string> = {
    starter: 'bg-gray-100 text-gray-700',
    professional: 'bg-blue-100 text-blue-700',
    enterprise: 'bg-purple-100 text-purple-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[plan] || 'bg-gray-100 text-gray-700'}`}>
      {plan}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: 'bg-green-100 text-green-700',
    onboarding: 'bg-yellow-100 text-yellow-700',
    suspended: 'bg-red-100 text-red-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  )
}
