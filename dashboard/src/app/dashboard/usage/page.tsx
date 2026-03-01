'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export default function UsagePage() {
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const data = await api.getMonthlyUsage()
        setUsage(data as Record<string, unknown>)
      } catch (err) {
        console.error('Failed to load usage:', err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) return <div className="text-gray-500">Loading...</div>

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Usage & Billing</h1>

      {usage && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <Card label="Conversations" value={String(usage.total_conversations)} />
            <Card label="Messages" value={String(usage.total_messages)} />
            <Card label="Tokens Used" value={Number(usage.total_tokens).toLocaleString()} />
            <Card label="Est. Cost" value={`$${Number(usage.total_cost).toFixed(2)}`} />
          </div>

          <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
            <h3 className="font-semibold text-gray-700 mb-4">Plan Details</h3>
            <div className="space-y-2 text-sm">
              <Row label="Current Plan" value={String(usage.plan).toUpperCase()} />
              <Row label="Included Conversations" value={String(usage.included_conversations)} />
              <Row label="Used" value={String(usage.total_conversations)} />
              <Row label="Remaining" value={String(usage.remaining_conversations)} />
              <Row label="Overage Conversations" value={String(usage.overage_conversations)} />
              <Row label="Overage Cost" value={`$${usage.overage_cost}`} />
            </div>
          </div>

          <div className="p-6 bg-white rounded-xl shadow-sm border">
            <h3 className="font-semibold text-gray-700 mb-4">Usage Bar</h3>
            <div className="w-full bg-gray-200 rounded-full h-4">
              <div
                className="bg-blue-600 h-4 rounded-full transition-all"
                style={{
                  width: `${Math.min(100, (Number(usage.total_conversations) / Number(usage.included_conversations)) * 100)}%`,
                }}
              />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              {usage.total_conversations} / {usage.included_conversations} conversations used
            </p>
          </div>
        </>
      )}
    </div>
  )
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-4 bg-white rounded-xl shadow-sm border">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-2xl font-bold text-gray-800 mt-1">{value}</p>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}
