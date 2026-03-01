'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export default function DashboardPage() {
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
          <StatCard label="Overage Cost" value={`$${usage.overage_cost}`} subtitle={`${usage.overage_conversations} extra conversations`} />
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, subtitle }: { label: string; value: string; subtitle: string }) {
  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-gray-800 mt-1">{value}</p>
      <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
    </div>
  )
}
