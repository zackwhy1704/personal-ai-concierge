'use client'
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'

interface Subscription {
  has_subscription: boolean
  plan: string
  status: string
  current_period_end?: string | null
  cancel_at_period_end: boolean
}

interface Usage {
  total_conversations: number
  total_messages: number
  total_tokens: number
  total_cost: number
  plan: string
  included_conversations: number
  remaining_conversations: number
  overage_conversations: number
  overage_cost: number
}

const PLANS = [
  { id: 'starter', name: 'Starter', price: 780, conversations: 500 },
  { id: 'professional', name: 'Professional', price: 2800, conversations: 2000 },
  { id: 'enterprise', name: 'Enterprise', price: 6800, conversations: 10000 },
]

export default function UsagePage() {
  return (
    <Suspense fallback={<div className="text-gray-500">Loading...</div>}>
      <UsageContent />
    </Suspense>
  )
}

function UsageContent() {
  const [usage, setUsage] = useState<Usage | null>(null)
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const searchParams = useSearchParams()
  const paymentStatus = searchParams.get('payment')

  useEffect(() => { loadData() }, [])

  async function loadData() {
    try {
      const [u, s] = await Promise.all([
        api.getMonthlyUsage(),
        api.getSubscriptionStatus(),
      ])
      setUsage(u as Usage)
      setSubscription(s as Subscription)
    } catch (err) {
      console.error('Failed to load data:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleSubscribe(plan: string) {
    setActionLoading(true)
    try {
      const result = await api.createCheckout(plan)
      window.location.href = result.checkout_url
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to create checkout')
    } finally {
      setActionLoading(false)
    }
  }

  async function handleCancel() {
    if (!confirm('Are you sure you want to cancel? Your service will continue until the end of the billing period.')) return
    setActionLoading(true)
    try {
      await api.cancelSubscription()
      loadData()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to cancel')
    } finally {
      setActionLoading(false)
    }
  }

  async function handleReactivate() {
    setActionLoading(true)
    try {
      await api.reactivateSubscription()
      loadData()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to reactivate')
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) return <div className="text-gray-500">Loading...</div>

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">Usage & Billing</h1>

      {/* Payment callback banners */}
      {paymentStatus === 'success' && (
        <div className="p-4 bg-green-50 border border-green-200 text-green-700 rounded-xl mb-6">
          Payment successful! Your subscription is now active.
        </div>
      )}
      {paymentStatus === 'cancelled' && (
        <div className="p-4 bg-yellow-50 border border-yellow-200 text-yellow-700 rounded-xl mb-6">
          Payment was cancelled. You can subscribe anytime from below.
        </div>
      )}

      {/* Subscription Status */}
      {subscription && (
        <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="font-semibold text-gray-700 mb-3">Subscription</h3>
              <div className="space-y-1 text-sm">
                <Row label="Status" value={
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    subscription.status === 'active' ? 'bg-green-100 text-green-700' :
                    subscription.status === 'past_due' ? 'bg-yellow-100 text-yellow-700' :
                    subscription.status === 'canceled' || subscription.status === 'none' ? 'bg-red-100 text-red-700' :
                    'bg-gray-100 text-gray-700'
                  }`}>
                    {subscription.status.toUpperCase()}
                  </span>
                } />
                <Row label="Plan" value={<span className="capitalize">{subscription.plan}</span>} />
                {subscription.current_period_end ? (
                  <Row label="Current Period Ends" value={
                    <span>{new Date(subscription.current_period_end).toLocaleDateString()}</span>
                  } />
                ) : null}
                {subscription.cancel_at_period_end ? (
                  <Row label="Cancellation" value={
                    <span className="text-orange-600">Will cancel at end of period</span>
                  } />
                ) : null}
              </div>
            </div>
            <div className="flex gap-2">
              {subscription.has_subscription && !subscription.cancel_at_period_end && (
                <button onClick={handleCancel} disabled={actionLoading}
                  className="px-3 py-1.5 text-sm border border-red-200 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-50">
                  Cancel
                </button>
              )}
              {subscription.cancel_at_period_end && (
                <button onClick={handleReactivate} disabled={actionLoading}
                  className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">
                  Reactivate
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Plan Selection (if no subscription) */}
      {subscription && !subscription.has_subscription && (
        <div className="mb-8">
          <h3 className="font-semibold text-gray-700 mb-4">Choose a Plan</h3>
          <div className="grid grid-cols-3 gap-4">
            {PLANS.map(plan => (
              <div key={plan.id} className="p-6 bg-white rounded-xl shadow-sm border text-center">
                <h4 className="font-bold text-lg">{plan.name}</h4>
                <p className="text-3xl font-bold text-gray-800 mt-2">RM{plan.price.toLocaleString()}<span className="text-sm text-gray-400">/mo</span></p>
                <p className="text-xs text-gray-500 mt-2">{plan.conversations.toLocaleString()} conversations included</p>
                <button onClick={() => handleSubscribe(plan.id)} disabled={actionLoading}
                  className="mt-4 w-full px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
                  Subscribe
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Usage Stats */}
      {usage && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <Card label="Conversations" value={String(usage.total_conversations)} />
            <Card label="Messages" value={String(usage.total_messages)} />
            <Card label="Tokens Used" value={usage.total_tokens.toLocaleString()} />
            <Card label="Est. Cost" value={`RM${usage.total_cost.toFixed(2)}`} />
          </div>

          <div className="p-6 bg-white rounded-xl shadow-sm border mb-6">
            <h3 className="font-semibold text-gray-700 mb-4">Plan Details</h3>
            <div className="space-y-2 text-sm">
              <Row label="Current Plan" value={<span>{usage.plan.toUpperCase()}</span>} />
              <Row label="Included Conversations" value={<span>{usage.included_conversations}</span>} />
              <Row label="Used" value={<span>{usage.total_conversations}</span>} />
              <Row label="Remaining" value={<span>{usage.remaining_conversations}</span>} />
              <Row label="Overage Conversations" value={<span>{usage.overage_conversations}</span>} />
              <Row label="Overage Cost" value={<span>RM{usage.overage_cost}</span>} />
            </div>
          </div>

          <div className="p-6 bg-white rounded-xl shadow-sm border">
            <h3 className="font-semibold text-gray-700 mb-4">Usage Bar</h3>
            <div className="w-full bg-gray-200 rounded-full h-4">
              <div
                className={`h-4 rounded-full transition-all ${
                  usage.total_conversations > usage.included_conversations
                    ? 'bg-red-500' : 'bg-blue-600'
                }`}
                style={{
                  width: `${Math.min(100, (usage.total_conversations / usage.included_conversations) * 100)}%`,
                }}
              />
            </div>
            <p className="text-xs text-gray-500 mt-2">
              {usage.total_conversations} / {usage.included_conversations} conversations used
              {usage.total_conversations > usage.included_conversations &&
                <span className="text-red-500 ml-2">(Overage!)</span>
              }
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

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}
