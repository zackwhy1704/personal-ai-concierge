'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

interface PromoCode {
  id: string
  code: string
  description: string | null
  trial_days: number
  max_redemptions: number | null
  times_redeemed: number
  is_active: boolean
  expires_at: string | null
  created_at: string
  stripe_coupon_id: string | null
  stripe_promo_id: string | null
}

export default function PromoCodesPage() {
  const [promos, setPromos] = useState<PromoCode[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    code: '',
    description: '',
    trial_days: '30',
    max_redemptions: '',
    expires_at: '',
  })

  useEffect(() => { loadPromos() }, [])

  async function loadPromos() {
    try {
      const data = await api.listPromoCodes()
      setPromos(data as unknown as PromoCode[])
    } catch (err) {
      console.error('Failed to load promo codes:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      const payload: Record<string, unknown> = {
        code: form.code,
        trial_days: parseInt(form.trial_days) || 30,
      }
      if (form.description) payload.description = form.description
      if (form.max_redemptions) payload.max_redemptions = parseInt(form.max_redemptions)
      if (form.expires_at) payload.expires_at = new Date(form.expires_at).toISOString()

      await api.createPromoCode(payload)
      setShowCreate(false)
      setForm({ code: '', description: '', trial_days: '30', max_redemptions: '', expires_at: '' })
      loadPromos()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to create promo code')
    } finally {
      setCreating(false)
    }
  }

  async function handleDeactivate(id: string, code: string) {
    if (!confirm(`Deactivate promo code "${code}"? This will also deactivate it in Stripe.`)) return
    try {
      await api.deactivatePromoCode(id)
      loadPromos()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to deactivate')
    }
  }

  async function handleDelete(id: string, code: string) {
    if (!confirm(`Permanently delete promo code "${code}"? This cannot be undone.`)) return
    try {
      await api.deletePromoCode(id)
      loadPromos()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete')
    }
  }

  if (loading) return <div className="text-gray-500">Loading...</div>

  const activeCount = promos.filter(p => p.is_active).length
  const totalRedemptions = promos.reduce((sum, p) => sum + p.times_redeemed, 0)

  return (
    <div className="max-w-4xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Promo Codes</h1>
        <button onClick={() => setShowCreate(!showCreate)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
          {showCreate ? 'Cancel' : '+ Create Promo Code'}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total Codes" value={String(promos.length)} />
        <StatCard label="Active" value={String(activeCount)} />
        <StatCard label="Total Redemptions" value={String(totalRedemptions)} />
      </div>

      {/* Create Form */}
      {showCreate && (
        <form onSubmit={handleCreate} className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <h3 className="font-semibold text-gray-700 mb-4">New Promo Code</h3>
          <div className="grid grid-cols-2 gap-3">
            <input value={form.code}
              onChange={e => setForm(p => ({ ...p, code: e.target.value.toUpperCase() }))}
              placeholder="Code (e.g. FREETRIAL)" className="px-3 py-2 border rounded-lg text-sm" required />
            <input value={form.description}
              onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
              placeholder="Description (optional)" className="px-3 py-2 border rounded-lg text-sm" />
            <div>
              <label className="block text-xs text-gray-500 mb-1">Trial Days</label>
              <input type="number" value={form.trial_days}
                onChange={e => setForm(p => ({ ...p, trial_days: e.target.value }))}
                min="1" className="w-full px-3 py-2 border rounded-lg text-sm" required />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Max Redemptions (blank = unlimited)</label>
              <input type="number" value={form.max_redemptions}
                onChange={e => setForm(p => ({ ...p, max_redemptions: e.target.value }))}
                min="1" placeholder="Unlimited" className="w-full px-3 py-2 border rounded-lg text-sm" />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-gray-500 mb-1">Expires At (optional)</label>
              <input type="datetime-local" value={form.expires_at}
                onChange={e => setForm(p => ({ ...p, expires_at: e.target.value }))}
                className="w-full px-3 py-2 border rounded-lg text-sm" />
            </div>
          </div>
          <p className="text-xs text-gray-400 mt-3">
            This creates a Stripe Coupon (100% off, 1 billing cycle) + Promotion Code. Customers enter the code on Stripe checkout.
          </p>
          <button type="submit" disabled={creating}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
            {creating ? 'Creating...' : 'Create Promo Code'}
          </button>
        </form>
      )}

      {/* Promo Code List */}
      <div className="space-y-3">
        {promos.map(promo => (
          <div key={promo.id} className={`p-4 bg-white rounded-xl shadow-sm border ${!promo.is_active ? 'opacity-60' : ''}`}>
            <div className="flex justify-between items-start">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-gray-800">{promo.code}</span>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    promo.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>
                    {promo.is_active ? 'Active' : 'Inactive'}
                  </span>
                  {promo.stripe_promo_id ? (
                    <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">Stripe</span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700">No Stripe</span>
                  )}
                </div>
                {promo.description && (
                  <p className="text-sm text-gray-500 mt-1">{promo.description}</p>
                )}
                <div className="flex gap-4 mt-2 text-xs text-gray-400">
                  <span>Trial: {promo.trial_days} days</span>
                  <span>Redeemed: {promo.times_redeemed}{promo.max_redemptions ? ` / ${promo.max_redemptions}` : ''}</span>
                  {promo.expires_at && (
                    <span>Expires: {new Date(promo.expires_at).toLocaleDateString()}</span>
                  )}
                  <span>Created: {new Date(promo.created_at).toLocaleDateString()}</span>
                </div>
              </div>
              <div className="flex gap-2 ml-4">
                {promo.is_active && (
                  <button onClick={() => handleDeactivate(promo.id, promo.code)}
                    className="px-3 py-1.5 text-sm border border-yellow-200 text-yellow-600 rounded-lg hover:bg-yellow-50">
                    Deactivate
                  </button>
                )}
                <button onClick={() => handleDelete(promo.id, promo.code)}
                  className="px-3 py-1.5 text-sm border border-red-200 text-red-600 rounded-lg hover:bg-red-50">
                  Delete
                </button>
              </div>
            </div>
          </div>
        ))}
        {promos.length === 0 && (
          <p className="text-gray-500 text-center py-8">No promo codes yet. Create one to get started.</p>
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-gray-800 mt-1">{value}</p>
    </div>
  )
}
